"""Library-wide achievement scan: one table showing completion % for every
game you own, so you can see at a glance what is close to 100%.

Each game is scanned in its own short-lived process (Steamworks is one AppID
per process). Results are cached to disk, so re-opening is instant.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import tkinter as tk
from tkinter import messagebox, ttk

import safety
import steamlib
from i18n import n, shape, t
from launcher import child_command
from settings import load_full_library
import theme
from theme import BG, BG_ALT, FG, FG_DIM

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_PATH = os.path.join(steamlib.CONFIG_DIR, "achievement_scan.json")
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _load_cache() -> dict:
    try:
        with open(CACHE_PATH, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


def _save_cache(data: dict) -> None:
    os.makedirs(steamlib.CONFIG_DIR, exist_ok=True)
    with open(CACHE_PATH, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False)


class ScanPage(tk.Frame):
    """Embedded page (was a Toplevel). Lives inside the main window's content
    area; the sidebar switches to it."""

    def __init__(self, parent: tk.Misc, dll_path: str, app=None):
        super().__init__(parent, bg=BG)
        self.app = app
        self.dll_path = dll_path
        self.games: list[steamlib.Game] = []
        self.results: dict[str, dict] = _load_cache()  # str(app_id) -> {total, unlocked}
        self._scanning = False
        self._cancel = False

        self.only_incomplete = tk.BooleanVar(value=False)
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self._redraw())

        self._build_ui()
        self.after(200, self._load_games)

    # ------------------------------------------------------------------- ui

    def _build_ui(self) -> None:
        header = tk.Frame(self, bg=BG_ALT)
        header.pack(fill="x")
        inner = tk.Frame(header, bg=BG_ALT, padx=18, pady=14)
        inner.pack(fill="x")
        tk.Label(
            inner, text=t("scan.header"), bg=BG_ALT, fg=FG, font=theme.font(15, "bold"),
        ).pack(side="left")

        theme.check(
            inner, t("scan.only_incomplete"), self.only_incomplete, self._redraw
        ).pack(side="right")

        theme.entry(inner, textvariable=self.search_var, width=18).pack(
            side="right", ipady=4, padx=(8, 14)
        )
        tk.Label(inner, text=t("search"), bg=BG_ALT, fg=FG_DIM).pack(side="right")
        tk.Frame(self, bg=theme.BORDER, height=1).pack(fill="x")

        body = tk.Frame(self, bg=BG, padx=14, pady=12)
        body.pack(fill="both", expand=True)

        columns = ("app", "name", "pct", "done", "total")
        self.tree = ttk.Treeview(body, columns=columns, show="headings", selectmode="browse")
        for key, text, width, anchor, stretch in (
            ("app", t("col.appid"), 70, "w", False),
            ("name", t("col.game"), 260, "w", True),
            ("pct", t("scan.col_pct"), 150, "w", False),
            ("done", t("scan.col_done"), 80, "center", False),
            ("total", t("scan.col_total"), 70, "center", False),
        ):
            self.tree.heading(key, text=text, command=lambda k=key: self._sort(k))
            self.tree.column(key, width=width, anchor=anchor, stretch=stretch)
        scrollbar = ttk.Scrollbar(body, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<Double-1>", lambda _: self._open_selected())
        self.tree.tag_configure("perfect", foreground=theme.SUCCESS)
        self.tree.tag_configure("close", foreground=theme.WARNING)
        self.tree.tag_configure("none", foreground=FG_DIM)
        self.tree.tag_configure("odd", background=BG_ALT)

        tk.Frame(self, bg=theme.BORDER, height=1).pack(fill="x")
        footer = tk.Frame(self, bg=BG_ALT, padx=18, pady=14)
        footer.pack(fill="x")
        self.status = tk.Label(footer, text="", bg=BG_ALT, fg=FG_DIM, anchor="w")
        self.status.pack(side="top", fill="x", pady=(0, 8))

        self.scan_button = theme.HoverButton(
            footer, text=t("scan.scan_button"), command=self._toggle_scan,
            kind="primary", padx=18, pady=8,
        )
        self.scan_button.pack(side="right")
        theme.HoverButton(
            footer, text=t("scan.open"), command=self._open_selected,
            kind="ghost", padx=12, pady=8,
        ).pack(side="right", padx=(0, 8))

        self._sort_key, self._sort_reverse = "pct", True

    # ----------------------------------------------------------------- data

    def _load_games(self) -> None:
        self.status.configure(text=t("scan.never"))

        def worker():
            try:
                games = load_full_library()
            except Exception as exc:
                safety.log_error("scan load_full_library", exc)
                games = steamlib.installed_games()
            self.after(0, lambda: self._games_loaded(games))

        threading.Thread(target=worker, daemon=True).start()

    def _games_loaded(self, games) -> None:
        if not self.winfo_exists():
            return
        self.games = games
        self._redraw()
        if self.results:
            self._update_status_idle()

    def _pct(self, app_id: int) -> int:
        entry = self.results.get(str(app_id))
        if not entry or not entry.get("total"):
            return -1
        return round(100 * entry["unlocked"] / entry["total"])

    def _visible(self):
        needle = self.search_var.get().strip().lower()
        rows = []
        for game in self.games:
            pct = self._pct(game.app_id)
            if self.only_incomplete.get() and (pct < 0 or pct >= 100):
                continue
            if needle and needle not in game.name.lower() and needle not in str(game.app_id):
                continue
            rows.append((game, pct))

        def key(item):
            game, pct = item
            if self._sort_key == "name":
                return game.name.lower()
            if self._sort_key == "app":
                return game.app_id
            if self._sort_key == "total":
                return (self.results.get(str(game.app_id)) or {}).get("total", -1)
            if self._sort_key == "done":
                return (self.results.get(str(game.app_id)) or {}).get("unlocked", -1)
            return pct  # pct

        return sorted(rows, key=key, reverse=self._sort_reverse)

    def _redraw(self) -> None:
        if not self.winfo_exists():
            return
        selected = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        for stripe, (game, pct) in enumerate(self._visible()):
            entry = self.results.get(str(game.app_id))
            if pct < 0:
                pct_text, done, total, tag = (
                    (t("scan.no_ach"), "", "", "none") if entry
                    else ("", "", "", "")
                )
            else:
                done = entry["unlocked"]
                total = entry["total"]
                pct_text = f"{theme.bar(pct / 100, 8)} {pct}%"
                tag = "perfect" if pct >= 100 else ("close" if pct >= 75 else "")
            tags = [tag] if tag else []
            if stripe % 2:
                tags.append("odd")
            self.tree.insert(
                "", "end", iid=str(game.app_id),
                values=(game.app_id, shape(game.name), pct_text, done, total),
                tags=tuple(tags),
            )
        for iid in selected:
            if self.tree.exists(iid):
                self.tree.selection_add(iid)

    def _sort(self, key: str) -> None:
        if self._sort_key == key:
            self._sort_reverse = not self._sort_reverse
        else:
            self._sort_key = key
            self._sort_reverse = key in ("pct", "done", "total")
        self._redraw()

    # ---------------------------------------------------------------- scan

    def _toggle_scan(self) -> None:
        if self._scanning:
            self._cancel = True
            return
        if not self.dll_path or not os.path.isfile(self.dll_path):
            messagebox.showerror(n("dll.title"), n("dll.required"), parent=self)
            return
        self._scanning = True
        self._cancel = False
        self.scan_button.configure(text=t("scan.stop"))
        # Skip games we already have; a re-scan of everything is the Refresh case.
        todo = [g for g in self.games]
        threading.Thread(target=self._scan_worker, args=(todo,), daemon=True).start()

    def _scan_worker(self, games) -> None:
        total = len(games)
        for index, game in enumerate(games, 1):
            if self._cancel:
                break
            self.after(0, lambda i=index, g=game: self._scan_progress(i, total, g.name))
            try:
                proc = subprocess.run(
                    child_command("scan", game.app_id, self.dll_path),
                    capture_output=True, text=True, encoding="utf-8",
                    errors="replace", timeout=30, cwd=HERE, creationflags=NO_WINDOW,
                )
                line = next(
                    (l for l in reversed(proc.stdout.splitlines()) if l.startswith("{")),
                    "",
                )
                data = json.loads(line) if line else {}
            except Exception as exc:
                safety.log_error(f"scan {game.app_id}", exc)
                data = {}

            if "total" in data:
                self.results[str(game.app_id)] = {
                    "total": data["total"],
                    "unlocked": data["unlocked"],
                }
                self.after(0, self._redraw)

        self.after(0, self._scan_done)

    def _scan_progress(self, i: int, total: int, name: str) -> None:
        if not self.winfo_exists():
            return
        self.status.configure(
            text=t("scan.scanning", done=i, total=total, game=shape(name)[:30])
        )

    def _scan_done(self) -> None:
        if not self.winfo_exists():
            return
        self._scanning = False
        self._cancel = False
        self.scan_button.configure(text=t("scan.scan_button"))
        _save_cache(self.results)
        with_ach = [e for e in self.results.values() if e.get("total")]
        perfect = [e for e in with_ach if e["unlocked"] >= e["total"]]
        self.status.configure(
            text=t("scan.done", withach=len(with_ach), perfect=len(perfect))
        )

    def _update_status_idle(self) -> None:
        scanned = len([e for e in self.results.values() if e.get("total")])
        self.status.configure(text=t("scan.idle", scanned=scanned))

    # -------------------------------------------------------------- launch

    def _open_selected(self) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        app_id = int(selection[0])
        name = next((g.name for g in self.games if g.app_id == app_id), f"AppID {app_id}")
        environment = dict(os.environ, SteamAppId=str(app_id), SteamGameId=str(app_id))
        try:
            subprocess.Popen(
                child_command("manager", app_id, self.dll_path, name),
                env=environment, cwd=HERE,
            )
        except OSError as exc:
            messagebox.showerror(
                n("app.title"), n("picker.launch_failed", error=exc), parent=self
            )

    def on_hide(self) -> None:
        """Called when the user switches away: stop scanning, persist cache."""
        self._cancel = True
        _save_cache(self.results)
