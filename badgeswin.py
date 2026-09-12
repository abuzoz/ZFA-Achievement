"""Badge tracker: what you own, what is missing, and what completing it costs.

Badges cannot be granted locally -- cards live in Steam's inventory servers --
so this window is about seeing the gap and pricing it, not faking it.
"""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox, ttk

from i18n import n, shape, t
from settings import get_web_client
from steamweb import Badge, SteamWeb
import theme
from theme import BG, BG_ALT, BORDER, FG, FG_DIM, apply_theme

XP_PER_CRAFT = 100  # Steam grants 100 XP per badge level crafted


def money(cents: int | None) -> str:
    return "—" if cents is None else f"{cents / 100:.2f}"


class BadgesPage(tk.Frame):
    """Embedded page (was a Toplevel), shown inside the main window."""

    def __init__(self, parent: tk.Misc, app=None):
        super().__init__(parent, bg=BG)
        self.app = app
        self.badges: dict[int, Badge] = {}
        self.client: SteamWeb | None = None
        self._busy = False
        self._sort_key = "missing"
        self._sort_reverse = True

        self._build_ui()
        self.after(200, self.reload)

    # ------------------------------------------------------------------- ui

    def _build_ui(self) -> None:
        header = tk.Frame(self, bg=BG_ALT)
        header.pack(fill="x")
        inner = tk.Frame(header, bg=BG_ALT, padx=18, pady=14)
        inner.pack(fill="x")
        self.level_label = tk.Label(
            inner,
            text=t("badges.level", level="—"),
            bg=BG_ALT,
            fg=FG,
            font=theme.font(15, "bold"),
        )
        self.level_label.pack(side="left")
        self.xp_label = tk.Label(inner, text="", bg=BG_ALT, fg=FG_DIM, font=theme.font(10))
        self.xp_label.pack(side="left", padx=14)
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")

        body = tk.Frame(self, bg=BG, padx=14, pady=12)
        body.pack(fill="both", expand=True)

        columns = ("app", "game", "badge", "level", "cards", "missing", "cost", "drops")
        self.tree = ttk.Treeview(body, columns=columns, show="headings", selectmode="browse")
        for key, text, width, anchor in (
            ("app", t("col.appid"), 75, "w"),
            ("game", t("col.game"), 260, "w"),
            ("badge", t("badges.col_badge"), 140, "w"),
            ("level", t("badges.col_level"), 45, "center"),
            ("cards", t("badges.col_cards"), 130, "w"),
            ("missing", t("badges.col_missing"), 70, "center"),
            ("cost", t("badges.col_cost"), 80, "e"),
            ("drops", t("badges.col_drops"), 60, "center"),
        ):
            self.tree.heading(key, text=text, command=lambda k=key: self._sort_by(k))
            self.tree.column(key, width=width, anchor=anchor, stretch=(key == "game"))
        scrollbar = ttk.Scrollbar(body, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<Double-1>", lambda _: self._show_details())
        self.tree.tag_configure("complete", foreground=theme.SUCCESS)
        self.tree.tag_configure("drops", foreground=theme.WARNING)
        self.tree.tag_configure("odd", background=BG_ALT)

        plan = tk.Frame(self, bg=BG, padx=16, pady=8)
        plan.pack(fill="x")
        self.plan_label = tk.Label(
            plan, text="", bg=BG, fg=theme.ACCENT_HI, anchor="w", justify="left",
            wraplength=860, font=theme.font(9),
        )
        self.plan_label.pack(fill="x")

        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")
        footer = tk.Frame(self, bg=BG_ALT, padx=18, pady=14)
        footer.pack(fill="x")
        self.status = tk.Label(footer, text="", bg=BG_ALT, fg=FG_DIM, anchor="w")
        self.status.pack(side="top", fill="x", pady=(0, 10))

        theme.HoverButton(
            footer, text=t("badges.fetch_prices"), command=self.fetch_prices,
            kind="primary", padx=18, pady=8,
        ).pack(side="right")

        for key, command in (
            ("btn.settings", lambda: self.app and self.app.show_page("settings")),
            ("badges.card_details", self._show_details),
            ("btn.reload", self.reload),
        ):
            theme.HoverButton(
                footer, text=t(key), command=command, kind="ghost", padx=12, pady=8,
            ).pack(side="right", padx=(0, 8))

    # ----------------------------------------------------------------- load

    def reload(self) -> None:
        if self._busy:
            return
        self.client = get_web_client()
        if self.client is None:
            self.status.configure(text=t("badges.no_profile"))
            if self.app is not None:
                self.app.show_page("settings")
            return

        self.badges.clear()
        self.tree.delete(*self.tree.get_children())
        self._busy = True
        self.status.configure(text=t("badges.loading"))

        def worker():
            client = self.client
            try:
                level = client.level_info()
                self.after(0, lambda: self._set_level(level))
                badges = client.badges(
                    progress=lambda text: self.after(
                        0, lambda w=text: self._set_status("badges.loading_page", what=w)
                    )
                )
            except Exception as exc:
                # Bind by default arg: `exc` is unbound once the except block
                # ends, so a plain closure would raise NameError later.
                self.after(0, lambda error=exc: self._fail(error))
                return

            for index, badge in enumerate(badges, 1):
                try:
                    cards, drops = client.card_set(badge.app_id)
                    badge.cards = cards
                    if cards:
                        badge.cards_total = len(cards)
                        badge.cards_owned = sum(1 for card in cards if card.owned)
                    badge.drops_remaining = max(badge.drops_remaining, drops)
                except Exception:
                    pass  # one unreadable set should not abort the whole scan
                self.after(
                    0,
                    lambda b=badge, i=index, total=len(badges): self._add(b, i, total),
                )

            self.after(0, self._finish_load)

        threading.Thread(target=worker, daemon=True).start()

    def _set_status(self, key: str, **kw) -> None:
        if self.winfo_exists():
            self.status.configure(text=t(key, **kw))

    def _set_level(self, level) -> None:
        if not self.winfo_exists():
            return
        self.level_label.configure(text=t("badges.level", level=level.level))
        self.xp_label.configure(
            text=t(
                "badges.xp",
                xp=f"{level.xp:,}",
                needed=level.xp_to_next,
                next_level=level.level + 1,
            )
        )
        self._xp_to_next = level.xp_to_next

    def _fail(self, exc: Exception) -> None:
        if not self.winfo_exists():
            return
        self._busy = False
        self.status.configure(text=t("badges.load_failed"))
        messagebox.showerror(
            n("steam.title"), n("badges.load_failed_detail", error=exc), parent=self
        )

    def _add(self, badge: Badge, index: int, total: int) -> None:
        if not self.winfo_exists():  # page navigated away while loading
            return
        self.badges[badge.app_id] = badge
        self.status.configure(text=t("badges.loading_sets", index=index, total=total))
        self._redraw()

    def _finish_load(self) -> None:
        if not self.winfo_exists():
            return
        self._busy = False
        incomplete = [b for b in self.badges.values() if b.missing]
        # Shape once, after joining: shaping each half separately would reverse
        # them independently and scramble the order in Arabic.
        self.status.configure(
            text=shape(
                n("badges.summary", total=len(self.badges), incomplete=len(incomplete))
                + ("" if self.client.logged_in else n("badges.no_cookie_suffix"))
            )
        )
        self._update_plan()

    # --------------------------------------------------------------- prices

    def fetch_prices(self) -> None:
        if self._busy or not self.badges:
            return
        if not self.client or not self.client.logged_in:
            messagebox.showwarning(
                n("badges.cookie_needed_title"),
                n("badges.cookie_needed"),
                parent=self,
            )
            return

        targets = [badge for badge in self.badges.values() if badge.missing]
        if not targets:
            messagebox.showinfo(
                n("badges.complete_title"), n("badges.nothing_missing"), parent=self
            )
            return

        self._busy = True

        def worker():
            failures = 0
            for index, badge in enumerate(targets, 1):
                try:
                    self.client.attach_prices(badge)
                except Exception:
                    failures += 1
                self.after(0, lambda i=index, f=failures: self._price_progress(i, f, len(targets)))
            self.after(0, lambda f=failures: self._finish_prices(f))

        threading.Thread(target=worker, daemon=True).start()

    def _price_progress(self, i: int, f: int, total: int) -> None:
        if not self.winfo_exists():
            return
        self.status.configure(
            text=shape(
                n("badges.fetching_prices", index=i, total=total)
                + (n("badges.failed_count", count=f) if f else "")
            )
        )
        self._redraw()

    def _finish_prices(self, failures: int) -> None:
        if not self.winfo_exists():
            return
        self._busy = False
        priced = [b for b in self.badges.values() if b.cost_cents is not None]
        total = sum(b.cost_cents for b in priced)
        self.status.configure(
            text=shape(
                n("badges.priced", count=len(priced), total=money(total))
                + (n("badges.rate_limited", count=failures) if failures else "")
            )
        )
        self._update_plan()

    # ------------------------------------------------------------------ ui

    def _sort_by(self, key: str) -> None:
        if self._sort_key == key:
            self._sort_reverse = not self._sort_reverse
        else:
            self._sort_key, self._sort_reverse = key, key in ("missing", "drops", "level")
        self._redraw()

    def _sort_value(self, badge: Badge):
        return {
            "app": badge.app_id,
            "game": badge.game_name.lower(),
            "badge": badge.badge_name.lower(),
            "level": badge.level,
            "cards": badge.cards_owned,
            "missing": badge.missing,
            "drops": badge.drops_remaining,
            "cost": badge.cost_cents if badge.cost_cents is not None else 10**9,
        }.get(self._sort_key, 0)

    def _redraw(self) -> None:
        selected = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        for stripe, badge in enumerate(
            sorted(self.badges.values(), key=self._sort_value, reverse=self._sort_reverse)
        ):
            if badge.drops_remaining:
                tags = ["drops"]
            elif not badge.missing:
                tags = ["complete"]
            else:
                tags = []
            if stripe % 2:
                tags.append("odd")
            if badge.cards_total:
                frac = badge.cards_owned / badge.cards_total
                cards = f"{theme.bar(frac, 6)} {badge.cards_owned}/{badge.cards_total}"
            else:
                cards = "—"
            self.tree.insert(
                "",
                "end",
                iid=str(badge.app_id),
                values=(
                    badge.app_id,
                    shape(badge.game_name),
                    shape(badge.badge_name),
                    badge.level,
                    cards,
                    badge.missing or "",
                    money(badge.cost_cents) if badge.missing else "",
                    badge.drops_remaining or "",
                ),
                tags=tuple(tags),
            )
        for iid in selected:
            if self.tree.exists(iid):
                self.tree.selection_add(iid)

    def _update_plan(self) -> None:
        needed = getattr(self, "_xp_to_next", 0)
        if not needed:
            self.plan_label.configure(text="")
            return

        crafts = -(-needed // XP_PER_CRAFT)  # ceil
        priced = sorted(
            (b for b in self.badges.values() if b.missing and b.cost_cents is not None),
            key=lambda b: b.cost_cents,
        )
        free = [b for b in self.badges.values() if b.drops_remaining]

        parts = [t("badges.plan_need", xp=needed, crafts=crafts)]
        if free:
            parts.append(
                t(
                    "badges.plan_free",
                    games=", ".join(
                        f"{b.game_name} ({b.drops_remaining})" for b in free[:4]
                    )
                    + ("…" if len(free) > 4 else ""),
                )
            )
        if priced:
            picks = priced[:crafts]
            total = sum(b.cost_cents for b in picks)
            parts.append(
                t(
                    "badges.plan_cheapest",
                    games=", ".join(
                        f"{b.game_name} ({money(b.cost_cents)})" for b in picks
                    ),
                    total=money(total),
                )
            )
        self.plan_label.configure(text="\n".join(parts))

    def _show_details(self) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        badge = self.badges.get(int(selection[0]))
        if badge:
            CardDetailWindow(self, badge)


class CardDetailWindow(tk.Toplevel):
    def __init__(self, parent: tk.Misc, badge: Badge):
        super().__init__(parent)
        self.title(n("badges.detail_title", game=badge.game_name))
        self.geometry("560x420")
        self.configure(bg=BG)
        apply_theme(self)

        tk.Label(
            self,
            text=t(
                "badges.detail_header",
                badge=shape(badge.badge_name) or t("badges.no_badge_yet"),
                owned=badge.cards_owned,
                total=badge.cards_total,
            ),
            bg=BG_ALT,
            fg=FG,
            anchor="w",
            padx=12,
            pady=8,
            font=("Segoe UI", 10, "bold"),
        ).pack(fill="x")

        tree = ttk.Treeview(
            self, columns=("card", "have", "price"), show="headings", selectmode="none"
        )
        for key, text, width, anchor in (
            ("card", t("badges.col_card"), 320, "w"),
            ("have", t("badges.col_have"), 60, "center"),
            ("price", t("badges.col_price"), 90, "e"),
        ):
            tree.heading(key, text=text)
            tree.column(key, width=width, anchor=anchor, stretch=(key == "card"))
        tree.tag_configure("missing", foreground="#ff7b72")
        tree.pack(fill="both", expand=True, padx=10, pady=10)

        for card in badge.cards:
            tree.insert(
                "",
                "end",
                values=(
                    shape(f"{card.index}  {card.name}" if card.index else card.name),
                    card.owned or "—",
                    card.price_text or "—",
                ),
                tags=() if card.owned else ("missing",),
            )

        tk.Label(
            self,
            text=t(
                "badges.detail_footer",
                count=badge.missing,
                cost=money(badge.cost_cents),
            ),
            bg=BG_ALT,
            fg=FG_DIM,
            anchor="w",
            padx=12,
            pady=8,
        ).pack(fill="x")
