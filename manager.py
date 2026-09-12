"""Achievement window for a single game. Launched as its own process because
Steamworks binds one AppID per process."""

from __future__ import annotations

import random
import sys
import tkinter as tk
from tkinter import messagebox, ttk

import backup
import safety
from i18n import n, shape, t
from steamapi import Achievement, SteamClient, SteamError
import theme
from theme import BG, BG_ALT, BORDER, FG, FG_DIM, apply_theme

try:
    from PIL import Image, ImageTk

    HAS_PIL = True
except ImportError:  # icons are optional, the tool works without them
    HAS_PIL = False


class ToggleBox(tk.Canvas):
    """A clearly-visible checkbox for the dark theme: a green box with a white
    check when unlocked, an empty bordered box when locked. Redraws itself when
    the bound variable changes (so Unlock-all / Invert / Undo stay in sync)."""

    SIZE = 26

    def __init__(self, parent, variable, command):
        super().__init__(
            parent, width=self.SIZE, height=self.SIZE, bg=BG,
            highlightthickness=0, bd=0, cursor="hand2",
        )
        self.var = variable
        self.command = command
        self.bind("<Button-1>", self._click)
        self._trace = self.var.trace_add("write", lambda *_: self._draw())
        self._draw()

    def _draw(self):
        self.delete("all")
        on = bool(self.var.get())
        s = self.SIZE
        theme.round_rect(
            self, 3, 3, s - 3, s - 3, 6,
            fill=theme.SUCCESS if on else BG_ALT,
            outline=theme.SUCCESS if on else theme.BORDER, width=2,
        )
        if on:
            self.create_line(
                8, 13, 11, 17, 18, 8, fill="#ffffff", width=2,
                capstyle="round", joinstyle="round",
            )

    def _click(self, _):
        self.var.set(not self.var.get())
        if self.command:
            self.command()


class AchievementRow:
    def __init__(self, parent: tk.Widget, achievement: Achievement, on_toggle):
        self.achievement = achievement
        self.var = tk.BooleanVar(value=achievement.unlocked)
        self.original = achievement.unlocked
        self._photo = None

        self.frame = tk.Frame(parent, bg=BG, padx=6, pady=4)

        self.check = ToggleBox(self.frame, self.var, on_toggle)
        self.check.grid(row=0, column=0, rowspan=2, padx=(2, 10))

        self.icon = tk.Label(self.frame, bg=BG, width=4, height=2)
        self.icon.grid(row=0, column=1, rowspan=2, padx=(0, 10))

        title = achievement.display_name
        if achievement.hidden:
            title += "  " + t("ach.hidden")
        tk.Label(
            self.frame,
            text=shape(title),
            bg=BG,
            fg=FG,
            font=("Segoe UI", 10, "bold"),
            anchor="w",
        ).grid(row=0, column=2, sticky="w")

        tk.Label(
            self.frame,
            text=shape(achievement.description or achievement.api_name),
            bg=BG,
            fg=FG_DIM,
            font=("Segoe UI", 9),
            anchor="w",
            wraplength=560,
            justify="left",
        ).grid(row=1, column=2, sticky="w")

        self.frame.columnconfigure(2, weight=1)

    @property
    def changed(self) -> bool:
        return self.var.get() != self.original

    def set_icon(self, image_data: tuple[int, int, bytes]) -> None:
        if not HAS_PIL:
            return
        width, height, rgba = image_data
        image = Image.frombytes("RGBA", (width, height), rgba).resize(
            (32, 32), Image.LANCZOS
        )
        self._photo = ImageTk.PhotoImage(image)
        self.icon.configure(image=self._photo, width=32, height=32)

    def matches(self, needle: str, locked_only: bool) -> bool:
        if locked_only and self.var.get():
            return False
        if not needle:
            return True
        haystack = " ".join(
            (
                self.achievement.display_name,
                self.achievement.description,
                self.achievement.api_name,
            )
        ).lower()
        return needle in haystack


class ManagerWindow(tk.Tk):
    def __init__(self, app_id: int, dll_path: str, game_name: str):
        super().__init__()
        self.app_id = app_id
        self.game_name = game_name
        self.rows: list[AchievementRow] = []
        self._pending_icons: list[AchievementRow] = []
        self._committing = False
        self._cancel_commit = False
        self._failed: list[str] = []

        self.title(n("ach.title", game=game_name, app_id=app_id))
        self.geometry("760x620")
        self.configure(bg=BG)
        apply_theme(self)
        safety.install(self)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        try:
            self.steam = SteamClient(dll_path, app_id)
        except SteamError as exc:
            messagebox.showerror(n("steam.title"), str(exc))
            self.destroy()
            raise SystemExit(1)

        self._build_ui()
        self.after(100, self._load_achievements)
        self.after(200, self._pump)

    # ------------------------------------------------------------------- ui

    def _build_ui(self) -> None:
        top = tk.Frame(self, bg=BG_ALT)
        top.pack(fill="x")
        inner = tk.Frame(top, bg=BG_ALT, padx=16, pady=12)
        inner.pack(fill="x")

        tk.Label(
            inner, text=t("ach.header"), bg=BG_ALT, fg=FG, font=theme.font(14, "bold"),
        ).pack(side="left")

        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self._refilter())
        theme.entry(inner, textvariable=self.search_var, width=24).pack(
            side="right", ipady=4, padx=(8, 0)
        )
        tk.Label(inner, text=t("search"), bg=BG_ALT, fg=FG_DIM).pack(side="right")

        self.locked_only = tk.BooleanVar(value=False)
        theme.check(
            inner, t("ach.locked_only"), self.locked_only, self._refilter
        ).pack(side="right", padx=12)
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")

        # Scrollable achievement list.
        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True)

        self.canvas = tk.Canvas(body, bg=BG, highlightthickness=0)
        scrollbar = ttk.Scrollbar(body, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)

        self.list_frame = tk.Frame(self.canvas, bg=BG)
        self.list_window = self.canvas.create_window(
            (0, 0), window=self.list_frame, anchor="nw"
        )
        self.list_frame.bind(
            "<Configure>",
            lambda _: self.canvas.configure(scrollregion=self.canvas.bbox("all")),
        )
        self.canvas.bind(
            "<Configure>",
            lambda event: self.canvas.itemconfigure(self.list_window, width=event.width),
        )
        self.bind_all("<MouseWheel>", self._on_wheel)

        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")
        bottom = tk.Frame(self, bg=BG_ALT, padx=16, pady=10)
        bottom.pack(fill="x")

        # Status on its own line so it never collides with the action buttons.
        self.status = tk.Label(
            bottom, text=t("ach.loading"), bg=BG_ALT, fg=FG_DIM, anchor="w"
        )
        self.status.pack(side="top", fill="x", pady=(0, 8))

        actions = tk.Frame(bottom, bg=BG_ALT)
        actions.pack(side="top", fill="x")

        self.commit_button = theme.HoverButton(
            actions, text=t("ach.commit"), command=self._commit, kind="primary",
            padx=16, pady=7, state="disabled",
        )
        self.commit_button.pack(side="right")

        self.spread = tk.BooleanVar(value=False)
        theme.check(actions, t("ach.spread"), self.spread).pack(side="right", padx=(0, 10))

        theme.HoverButton(
            actions, text=t("ach.restore"), command=self._restore_backup,
            kind="danger", padx=11, pady=7,
        ).pack(side="right", padx=(0, 6))
        for key, command in (
            ("ach.invert", self._invert),
            ("ach.lock_all", lambda: self._set_all(False)),
            ("ach.unlock_all", lambda: self._set_all(True)),
        ):
            theme.HoverButton(
                actions, text=t(key), command=command, kind="ghost", padx=11, pady=7,
            ).pack(side="right", padx=(0, 6))

    def _on_wheel(self, event) -> None:
        self.canvas.yview_scroll(int(-event.delta / 120), "units")

    # ------------------------------------------------------------------ data

    def _load_achievements(self, attempt: int = 0) -> None:
        self.steam.request_stats()
        self.steam.run_callbacks()

        achievements = self.steam.achievements()
        if not achievements:
            if attempt < 25:  # stats arrive asynchronously; ~5s of retries
                self.status.configure(text=t("ach.waiting", attempt=attempt + 1))
                self.after(200, lambda: self._load_achievements(attempt + 1))
                return
            self.status.configure(text=t("ach.none"))
            messagebox.showwarning(n("steam.title"), n("ach.none_detail"))
            return

        for achievement in achievements:
            row = AchievementRow(self.list_frame, achievement, self._update_state)
            self.rows.append(row)
            self._pending_icons.append(row)

        self._refilter()
        self._update_state()

    def _pump(self) -> None:
        """Keep Steam callbacks flowing and attach icons as they arrive."""
        if not self.winfo_exists():  # window closed -> stop the loop
            return
        self.steam.run_callbacks()
        still_pending = []
        for row in self._pending_icons:
            data = self.steam.icon_rgba(row.achievement.api_name)
            if data:
                row.set_icon(data)
            else:
                still_pending.append(row)
        self._pending_icons = still_pending
        self.after(300, self._pump)

    def _refilter(self) -> None:
        needle = self.search_var.get().strip().lower()
        locked_only = self.locked_only.get()
        for row in self.rows:
            row.frame.pack_forget()
        for row in self.rows:
            if row.matches(needle, locked_only):
                row.frame.pack(fill="x", anchor="w")
        self.canvas.yview_moveto(0)

    def _set_all(self, value: bool) -> None:
        for row in self.rows:
            if row.frame.winfo_ismapped():
                row.var.set(value)
        self._update_state()

    def _invert(self) -> None:
        for row in self.rows:
            if row.frame.winfo_ismapped():
                row.var.set(not row.var.get())
        self._update_state()

    def _update_state(self) -> None:
        unlocked = sum(1 for row in self.rows if row.var.get())
        changed = [row for row in self.rows if row.changed]
        if self._committing:
            return  # button is "Stop" mid-run; leave the status line alone
        self.status.configure(
            text=t(
                "ach.status",
                unlocked=unlocked,
                total=len(self.rows),
                changed=len(changed),
            )
        )
        self.commit_button.configure(state="normal" if changed else "disabled")

    # Average seconds between unlocks when spreading; jittered per step.
    SPREAD_STEP_SECONDS = 20

    def _commit(self) -> None:
        if self._committing:
            self._cancel_commit = True
            return

        changed = [row for row in self.rows if row.changed]
        if not changed:
            return

        spread = self.spread.get() and len(changed) > 1
        if spread:
            minutes = max(1, round(len(changed) * self.SPREAD_STEP_SECONDS / 60))
            prompt = n(
                "ach.confirm_spread",
                count=len(changed),
                game=self.game_name,
                minutes=minutes,
            )
        else:
            prompt = n("ach.confirm", count=len(changed), game=self.game_name)
        if not messagebox.askyesno(n("ach.confirm_title"), prompt):
            return

        # Snapshot the current state before touching anything, so Undo works.
        backup.save_snapshot(
            self.app_id, self.game_name, [row.achievement for row in self.rows]
        )

        self._committing = True
        self._cancel_commit = False
        self._failed: list[str] = []
        self.commit_button.configure(text=t("ach.stop"))
        # Randomise order so a spread unlock does not follow list order.
        queue = list(changed)
        if spread:
            random.shuffle(queue)
        self._apply_next(queue, 0, len(queue), spread)

    def _apply_next(self, queue, index, total, spread) -> None:
        if self._cancel_commit or index >= len(queue):
            self._finish_commit(index)
            return

        row = queue[index]
        if not self.steam.set_achievement(row.achievement.api_name, row.var.get()):
            self._failed.append(row.achievement.display_name)
        # Persist after each change so a stop mid-way still saves progress.
        self.steam.store()
        for _ in range(5):
            self.steam.run_callbacks()
        row.original = row.var.get()
        self._update_state()
        self.status.configure(text=t("ach.committing", done=index + 1, total=total))

        if not spread:
            self._apply_next(queue, index + 1, total, spread)
            return
        delay = int(self.SPREAD_STEP_SECONDS * random.uniform(0.4, 1.6) * 1000)
        self.after(delay, lambda: self._apply_next(queue, index + 1, total, spread))

    def _finish_commit(self, done) -> None:
        self._committing = False
        self.commit_button.configure(text=t("ach.commit"))
        self._update_state()
        if self._failed:
            messagebox.showwarning(
                n("steam.title"),
                n("ach.partial_failed", names="\n".join(self._failed[:15])),
            )
        else:
            self.status.configure(text=t("ach.commit_done", count=done))

    def _restore_backup(self) -> None:
        snapshot = backup.latest_snapshot(self.app_id)
        if not snapshot:
            messagebox.showinfo(n("steam.title"), n("ach.no_backup"))
            return

        state = snapshot["state"]
        to_revert = [
            row
            for row in self.rows
            if row.achievement.api_name in state
            and row.var.get() != state[row.achievement.api_name]
        ]
        if not to_revert:
            self.status.configure(text=t("ach.commit_done", count=0))
            return
        if not messagebox.askyesno(
            n("ach.confirm_title"),
            n("ach.restore_confirm", when=snapshot["when"], count=len(to_revert)),
        ):
            return

        for row in to_revert:
            target = state[row.achievement.api_name]
            row.var.set(target)
            self.steam.set_achievement(row.achievement.api_name, target)
        self.steam.store()
        for _ in range(10):
            self.steam.run_callbacks()
        for row in self.rows:
            row.original = row.var.get()
        self._update_state()
        messagebox.showinfo(n("ach.saved_title"), n("ach.restored", count=len(to_revert)))

    def _on_close(self) -> None:
        self._cancel_commit = True
        try:
            self.steam.close()
        finally:
            self.destroy()


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: manager.py <app_id> <dll_path> [game_name]")
        return 2
    app_id = int(sys.argv[1])
    dll_path = sys.argv[2]
    game_name = sys.argv[3] if len(sys.argv) > 3 else f"AppID {app_id}"
    # This runs as its own process (pythonw discards stderr), so a crash before
    # the window shows would be invisible -- log it and surface a dialog.
    try:
        ManagerWindow(app_id, dll_path, game_name).mainloop()
    except SystemExit:
        raise
    except BaseException as exc:  # noqa: BLE001
        safety.log_error(f"manager {app_id} ({game_name})", exc)
        try:
            from tkinter import messagebox

            messagebox.showerror(n("steam.title"), str(exc))
        except Exception:
            pass
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
