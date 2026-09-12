"""Idler: makes Steam count a game as running without launching it.

Two uses share the same mechanism -- accruing the card drops you are still
owed, and accruing playtime hours. The game does not need to be installed.
"""

from __future__ import annotations

import os
import subprocess
import threading
import time
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

import safety
import steamlib
from i18n import n, shape, t
from launcher import child_command
from settings import get_web_client, load_full_library
import theme
from theme import BG, BG_ALT, BORDER, SURFACE, FG, FG_DIM

HERE = os.path.dirname(os.path.abspath(__file__))
MAX_CONCURRENT = 20  # Steam stops counting playtime somewhere above ~32
RECHECK_SECONDS = 600
PLAYTIME_REFRESH_SECONDS = 300

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class IdleJob:
    def __init__(self, app_id: int, name: str, process: subprocess.Popen):
        self.app_id = app_id
        self.name = name
        self.process = process
        self.started = time.monotonic()
        self.last_line = ""
        self.stopped_by_user = False
        self.restarts = 0
        self._saw_error = False
        self._started_ok = False
        self._ended_at: float | None = None  # frozen end time once not alive
        threading.Thread(target=self._drain, daemon=True).start()

    def _drain(self) -> None:
        if not self.process.stdout:
            return
        for line in self.process.stdout:
            line = line.strip()
            if not line:
                continue
            # Remember these even if more output follows them.
            if line.startswith("ERROR"):
                self._saw_error = True
            elif line.startswith("IDLING"):
                self._started_ok = True
            self.last_line = line

    @property
    def alive(self) -> bool:
        return self.process.poll() is None

    @property
    def seconds(self) -> int:
        # Freeze the session clock the moment the process is no longer running.
        if self.process.poll() is None:
            return int(time.monotonic() - self.started)
        if self._ended_at is None:
            self._ended_at = time.monotonic()
        return int(self._ended_at - self.started)

    @property
    def elapsed(self) -> str:
        total = self.seconds
        return f"{total // 3600:02d}:{total % 3600 // 60:02d}:{total % 60:02d}"

    @property
    def failed(self) -> bool:
        """The game refused to start -- never reached the idling loop."""
        if self._saw_error:
            return True
        return not self._started_ok and self.process.poll() not in (None, 0)

    @property
    def finished(self) -> bool:
        """Ended on purpose: the user stopped it, or its time limit expired."""
        return self.stopped_by_user or self.last_line.startswith("DONE")

    @property
    def crashed(self) -> bool:
        """Idled for a while, then died on its own -- worth restarting. A game
        that dies within seconds of starting isn't idleable (e.g. a non-game
        app Steam refuses), so don't loop-restart it."""
        return (
            self._started_ok
            and not self.alive
            and not self.finished
            and self.seconds >= 25
        )

    def stop(self) -> None:
        self.stopped_by_user = True
        if self.alive:
            self.process.terminate()


class IdlerPage(tk.Frame):
    """Embedded page. Idle jobs (subprocesses) keep running when you switch to
    another page -- the frame stays alive, we just hide it."""

    def __init__(self, parent: tk.Misc, dll_path: str, app=None):
        super().__init__(parent, bg=BG)
        self.app = app
        self.dll_path = dll_path
        self.jobs: dict[int, IdleJob] = {}
        self.rows: dict[int, dict] = {}  # app_id -> {name, drops, minutes}
        config = steamlib.load_config()
        # Ticked games persist, so an auto-start / reboot resumes the same set.
        self.checked: set[int] = set(config.get("idler_checked", []))
        self._last_recheck = 0.0
        self._last_playtime_refresh = time.monotonic()
        self._loading = False

        self.drops_only = tk.BooleanVar(value=False)
        self.limit_hours = tk.StringVar(value="")
        self.auto_start = tk.BooleanVar(value=bool(config.get("idler_auto_start")))
        self._restarted = 0
        self._auto_started = False

        self._build_ui()
        self._tick()
        self.after(300, self.refresh)

    # ------------------------------------------------------------------- ui

    def _build_ui(self) -> None:
        header = tk.Frame(self, bg=BG_ALT)
        header.pack(fill="x")
        inner = tk.Frame(header, bg=BG_ALT, padx=18, pady=14)
        inner.pack(fill="x")
        tk.Label(
            inner, text=t("idler.header"), bg=BG_ALT, fg=FG, font=theme.font(15, "bold"),
        ).pack(side="left")
        self.header_note = tk.Label(
            inner, text="", bg=SURFACE, fg=FG_DIM, font=theme.font(9), padx=10, pady=3
        )
        self.header_note.pack(side="left", padx=12)

        theme.check(
            inner, t("idler.auto_start"), self.auto_start, self._save_auto_start
        ).pack(side="right", padx=(0, 14))
        theme.check(
            inner, t("idler.drops_only"), self.drops_only, self._redraw
        ).pack(side="right")

        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self._redraw())
        theme.entry(inner, textvariable=self.search_var, width=18).pack(
            side="right", ipady=4, padx=(8, 14)
        )
        tk.Label(inner, text=t("search"), bg=BG_ALT, fg=FG_DIM).pack(side="right")
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")

        body = tk.Frame(self, bg=BG, padx=14, pady=12)
        body.pack(fill="both", expand=True)

        columns = ("check", "app", "name", "hours", "drops", "state", "session")
        self.tree = ttk.Treeview(
            body, columns=columns, show="headings", selectmode="extended"
        )
        for key, text, width, anchor, stretch in (
            ("check", "☐", 40, "center", False),
            ("app", t("col.appid"), 75, "w", False),
            ("name", t("col.game"), 300, "w", True),
            ("hours", t("idler.col_playtime"), 110, "e", False),
            ("drops", t("idler.col_drops"), 60, "center", False),
            ("state", t("idler.col_state"), 110, "w", False),
            ("session", t("idler.col_session"), 85, "e", False),
        ):
            self.tree.heading(
                key, text=text,
                command=self._toggle_all_checks if key == "check" else "",
            )
            self.tree.column(key, width=width, anchor=anchor, stretch=stretch)
        scrollbar = ttk.Scrollbar(body, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        # Click in the checkbox column toggles that game's selection.
        self.tree.bind("<Button-1>", self._on_tree_click, add="+")
        # Right-click a game -> stop/start just that one.
        self.tree.bind("<Button-3>", self._show_context_menu, add="+")
        self.tree.tag_configure("running", foreground=theme.SUCCESS)
        self.tree.tag_configure("failed", foreground=theme.DANGER)
        self.tree.tag_configure("stopped", foreground=FG_DIM)
        self.tree.tag_configure("drops", foreground=theme.WARNING)
        self.tree.tag_configure("odd", background=BG_ALT)

        limit = tk.Frame(self, bg=BG, padx=16, pady=4)
        limit.pack(fill="x")
        tk.Label(limit, text=t("idler.run_for"), bg=BG, fg=FG_DIM).pack(side="left")
        theme.entry(
            limit, textvariable=self.limit_hours, width=6, justify="center"
        ).pack(side="left", padx=8, ipady=4)
        tk.Label(limit, text=t("idler.run_for_suffix"), bg=BG, fg=FG_DIM).pack(side="left")

        tk.Frame(self, bg=BORDER, height=1).pack(fill="x", pady=(8, 0))
        footer = tk.Frame(self, bg=BG_ALT, padx=18, pady=14)
        footer.pack(fill="x")
        self.status = tk.Label(footer, text="", bg=BG_ALT, fg=FG_DIM, anchor="w")
        self.status.pack(side="top", fill="x", pady=(0, 10))

        theme.HoverButton(
            footer, text=t("idler.start_selected"), command=self._start_selected,
            kind="primary", padx=18, pady=8,
        ).pack(side="right")

        for key, command in (
            ("idler.stop_all", self._stop_all),
            ("idler.stop_selected", self._stop_selected),
            ("idler.start_all_drops", self._start_all_drops),
            ("idler.add_appid", self._add_manual),
            ("btn.refresh", self.refresh),
        ):
            theme.HoverButton(
                footer, text=t(key), command=command, kind="ghost", padx=11, pady=8,
            ).pack(side="right", padx=(0, 8))

    # ----------------------------------------------------------------- data

    def refresh(self) -> None:
        if self._loading:
            return
        self._loading = True
        self.header_note.configure(text=t("idler.loading"))

        def worker():
            try:
                games = load_full_library(
                    progress=lambda index, total: self.after(
                        0,
                        lambda: self.header_note.configure(
                            text=t("picker.resolving_names", index=index, total=total)
                        ),
                    )
                )
            except Exception as exc:
                # `exc` is unbound after the except block; bind it as a default.
                self.after(0, lambda error=exc: self._load_failed(error))
                return

            entries = {
                game.app_id: {
                    "app_id": game.app_id,
                    "name": game.name,
                    "minutes": game.playtime_minutes,
                    "drops": -1,
                }
                for game in games
            }

            note = t("idler.note_no_cookie", count=len(entries))
            client = get_web_client()
            if client is not None and client.logged_in:
                try:
                    badges = client.badges()
                    for badge in badges:
                        entry = entries.setdefault(
                            badge.app_id,
                            {
                                "app_id": badge.app_id,
                                "name": badge.game_name,
                                "minutes": 0,
                                "drops": 0,
                            },
                        )
                        entry["drops"] = badge.drops_remaining
                    waiting = sum(max(0, b.drops_remaining) for b in badges)
                    note = t("idler.note_drops", count=len(entries), waiting=waiting)
                except Exception as exc:
                    note = t("idler.note_drops_failed", count=len(entries), error=exc)

            self.after(0, lambda: self._loaded(entries, note))

        threading.Thread(target=worker, daemon=True).start()

    def _loaded(self, entries: dict[int, dict], note: str) -> None:
        if not self.winfo_exists():
            return
        self._loading = False
        for app_id, entry in entries.items():
            existing = self.rows.get(app_id)
            if existing:
                existing.update(entry)
            else:
                self.rows[app_id] = entry
        self.header_note.configure(text=note)
        self._redraw()

        if self.auto_start.get() and not self._auto_started:
            self._auto_started = True
            # Resume the games you ticked (works without a cookie); if none are
            # ticked, fall back to whatever still has card drops.
            ready = [a for a in self.checked if a in self.rows]
            if not ready:
                ready = [a for a, row in self.rows.items() if row["drops"] > 0]
            if ready:
                self._start_many(ready, quiet=True)

    def _load_failed(self, exc: Exception) -> None:
        if not self.winfo_exists():
            return
        self._loading = False
        self.header_note.configure(text=t("idler.load_failed"))
        messagebox.showerror(
            n("steam.title"), n("picker.library_failed", error=exc), parent=self
        )

    def _refresh_playtime(self) -> None:
        """Steam flushes localconfig.vdf periodically; pick up the new totals."""

        def worker():
            try:
                minutes = steamlib.local_library_apps()
            except Exception:
                return
            self.after(0, lambda: self._apply_playtime(minutes))

        threading.Thread(target=worker, daemon=True).start()

    def _apply_playtime(self, minutes: dict[int, int]) -> None:
        for app_id, value in minutes.items():
            if app_id in self.rows:
                self.rows[app_id]["minutes"] = max(self.rows[app_id]["minutes"], value)
        self._redraw()

    # ------------------------------------------------------------------ view

    def _visible_rows(self) -> list[dict]:
        needle = self.search_var.get().strip().lower()
        rows = []
        for entry in self.rows.values():
            if self.drops_only.get() and entry["drops"] <= 0:
                continue
            if needle and needle not in entry["name"].lower() and needle not in str(
                entry["app_id"]
            ):
                continue
            rows.append(entry)
        return sorted(rows, key=lambda e: (-e["drops"], -e["minutes"], e["name"].lower()))

    def _playtime_text(self, entry: dict) -> str:
        hours = entry["minutes"] / 60
        job = self.jobs.get(entry["app_id"])
        if job and job.alive:
            return f"{hours:.1f}h  +{job.seconds / 3600:.2f}"
        return f"{hours:.1f}h" if entry["minutes"] else "—"

    def _redraw(self) -> None:
        if not self.winfo_exists():
            return
        selection = set(self.tree.selection())
        self.tree.delete(*self.tree.get_children())
        for stripe, entry in enumerate(self._visible_rows()):
            app_id = entry["app_id"]
            job = self.jobs.get(app_id)
            if job and job.alive:
                state, session, tag = "● " + t("idler.state_idling"), job.elapsed, "running"
            elif job and job.failed:
                state, session, tag = "✕ " + t("idler.state_skipped"), job.elapsed, "failed"
            elif job:
                state, session, tag = t("idler.state_stopped"), job.elapsed, "stopped"
            elif entry["drops"] > 0:
                state, session, tag = "", "", "drops"
            else:
                state, session, tag = "", "", ""
            tags = [tag] if tag else []
            if stripe % 2:
                tags.append("odd")
            self.tree.insert(
                "",
                "end",
                iid=str(app_id),
                values=(
                    "☑" if app_id in self.checked else "☐",
                    app_id,
                    shape(entry["name"]),
                    self._playtime_text(entry),
                    entry["drops"] if entry["drops"] > 0 else ("?" if entry["drops"] < 0 else ""),
                    state,
                    session,
                ),
                tags=tuple(tags),
            )
        for iid in selection:
            if self.tree.exists(iid):
                self.tree.selection_add(iid)
        checked_vis = sum(1 for e in self._visible_rows() if e["app_id"] in self.checked)
        self.tree.heading("check", text="☑" if checked_vis else "☐")

    def _save_checked(self) -> None:
        config = steamlib.load_config()
        config["idler_checked"] = sorted(self.checked)
        steamlib.save_config(config)

    def _on_tree_click(self, event) -> None:
        """A click in the checkbox column toggles that game's tick."""
        if self.tree.identify_region(event.x, event.y) != "cell":
            return
        if self.tree.identify_column(event.x) != "#1":  # the check column
            return
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        app_id = int(iid)
        if app_id in self.checked:
            self.checked.discard(app_id)
        else:
            self.checked.add(app_id)
        self._save_checked()
        self._redraw()

    def _toggle_all_checks(self) -> None:
        """Header click: tick or untick every currently visible game."""
        visible = [e["app_id"] for e in self._visible_rows()]
        if all(a in self.checked for a in visible) and visible:
            self.checked.difference_update(visible)
        else:
            self.checked.update(visible)
        self._save_checked()
        self._redraw()

    def _show_context_menu(self, event) -> None:
        """Right-click a game: stop just it, start just it, or (un)tick it."""
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        app_id = int(iid)
        self.tree.selection_set(iid)
        job = self.jobs.get(app_id)

        menu = tk.Menu(
            self, tearoff=0, bg=SURFACE, fg=FG, activebackground=theme.ACCENT_DIM,
            activeforeground="#ffffff", bd=0, relief="flat", font=theme.font(10),
        )
        if job is not None and job.alive:
            menu.add_command(
                label=n("idler.ctx_stop"), command=lambda: self._stop_one(app_id)
            )
        else:
            menu.add_command(
                label=n("idler.ctx_start"), command=lambda: self._start_one(app_id)
            )
        menu.add_separator()
        if app_id in self.checked:
            menu.add_command(
                label=n("idler.ctx_uncheck"),
                command=lambda: self._context_toggle_check(app_id),
            )
        else:
            menu.add_command(
                label=n("idler.ctx_check"),
                command=lambda: self._context_toggle_check(app_id),
            )
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _stop_one(self, app_id: int) -> None:
        job = self.jobs.get(app_id)
        if job is not None:
            job.stop()
        self._redraw()

    def _start_one(self, app_id: int) -> None:
        self._start_many([app_id])

    def _context_toggle_check(self, app_id: int) -> None:
        if app_id in self.checked:
            self.checked.discard(app_id)
        else:
            self.checked.add(app_id)
        self._save_checked()
        self._redraw()

    # -------------------------------------------------------------- control

    def _limit_minutes(self) -> float:
        raw = self.limit_hours.get().strip()
        if not raw:
            return 0.0
        try:
            return max(0.0, float(raw)) * 60
        except ValueError:
            return 0.0

    def _selected_ids(self) -> list[int]:
        # Ticked checkboxes win; otherwise fall back to the highlighted rows.
        if self.checked:
            return [a for a in self.checked if str(a) in self.tree.get_children()]
        return [int(iid) for iid in self.tree.selection()]

    def _start_selected(self) -> None:
        ids = self._selected_ids()
        if not ids:
            messagebox.showinfo(
                n("app.title"), n("idler.select_first"), parent=self
            )
            return
        self._start_many(ids)
        self._verify_started(list(ids))

    def _start_all_drops(self) -> None:
        ids = [app_id for app_id, entry in self.rows.items() if entry["drops"] > 0]
        if not ids:
            messagebox.showinfo(
                n("idler.none_title"), n("idler.no_drops"), parent=self
            )
            return
        self._start_many(ids)
        self._verify_started(list(ids))

    def _verify_started(self, ids: list[int], attempt: int = 0) -> None:
        """A moment after starting, confirm how many actually reached the idling
        state and report which (if any) refused to run."""
        pending = [
            a for a in ids
            if (job := self.jobs.get(a)) is not None
            and job.alive and not job._started_ok and not job.failed
        ]
        if pending and attempt < 8:  # give processes a few seconds to spin up
            self.after(1000, lambda: self._verify_started(ids, attempt + 1))
            return

        running = [a for a in ids if (j := self.jobs.get(a)) is not None and j.alive]
        failed = [a for a in ids if a not in running]
        message = n("idler.start_result", ok=len(running), total=len(ids))
        if failed:
            names = [self.rows.get(a, {}).get("name", f"AppID {a}") for a in failed]
            message += "\n\n" + n("idler.start_failed_list", names="\n".join(names[:12]))
        messagebox.showinfo(n("idler.title"), message, parent=self)

    def _start_many(self, ids: list[int], quiet: bool = False) -> None:
        running = sum(1 for job in self.jobs.values() if job.alive)
        started = 0
        for app_id in ids:
            job = self.jobs.get(app_id)
            if job and job.alive:
                continue
            if job and job.failed:
                continue  # this game refuses Steamworks; do not keep retrying
            if running + started >= MAX_CONCURRENT:
                if not quiet:
                    messagebox.showwarning(
                        n("idler.max_title"),
                        n("idler.max_reached", max=MAX_CONCURRENT),
                        parent=self,
                    )
                break
            if self._start(app_id, quiet=quiet):
                started += 1
        self._redraw()

    def _start(self, app_id: int, quiet: bool = False) -> bool:
        name = self.rows.get(app_id, {}).get("name", f"AppID {app_id}")
        limit = self._limit_minutes()
        args = [app_id, self.dll_path]
        if limit:
            args.append(limit)
        command = child_command("idle", *args)
        try:
            process = subprocess.Popen(
                command,
                cwd=HERE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                # Steamworks writes non-UTF-8 bytes to stdout; never let the
                # reader thread die on a decode error.
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=NO_WINDOW,
            )
        except OSError as exc:
            safety.log_error(f"idle start {app_id}", exc)
            if not quiet:
                messagebox.showerror(
                    n("app.title"),
                    n("idler.start_failed", game=name, error=exc),
                    parent=self,
                )
            return False
        previous = self.jobs.get(app_id)
        job = IdleJob(app_id, name, process)
        if previous is not None:
            job.restarts = previous.restarts
        self.jobs[app_id] = job
        return True

    def _stop_selected(self) -> None:
        for app_id in self._selected_ids():
            job = self.jobs.get(app_id)
            if job:
                job.stop()
        self._redraw()

    def _stop_all(self) -> None:
        for job in self.jobs.values():
            job.stop()
        self._redraw()

    def _add_manual(self) -> None:
        raw = simpledialog.askstring(
            n("col.appid"), n("idler.appid_prompt"), parent=self
        )
        if not raw or not raw.strip().isdigit():
            return
        app_id = int(raw.strip())
        self.rows.setdefault(
            app_id,
            {"app_id": app_id, "name": f"AppID {app_id}", "minutes": 0, "drops": -1},
        )
        self._redraw()

    # ----------------------------------------------------------------- loop

    def _tick(self) -> None:
        if not self.winfo_exists():  # page destroyed -> stop the loop
            return
        running = [job for job in self.jobs.values() if job.alive]
        failed = [
            job
            for job in self.jobs.values()
            if not job.alive and job.last_line.startswith("ERROR")
        ]
        self._revive_crashed()
        session_hours = sum(job.seconds for job in running) / 3600
        # Join before shaping: two separately shaped halves would render in the
        # wrong order in Arabic.
        self.status.configure(
            text=shape(
                n("idler.status", running=len(running), hours=f"{session_hours:.2f}")
                + (n("idler.status_failed", count=len(failed)) if failed else "")
                + (
                    n("idler.status_restarted", count=self._restarted)
                    if self._restarted
                    else ""
                )
            )
        )
        self._redraw()

        now = time.monotonic()
        if running and now - self._last_recheck > RECHECK_SECONDS:
            self._last_recheck = now
            self._recheck_drops([job.app_id for job in running])
        if now - self._last_playtime_refresh > PLAYTIME_REFRESH_SECONDS:
            self._last_playtime_refresh = now
            self._refresh_playtime()

        self.after(1000, self._tick)

    def _save_auto_start(self) -> None:
        config = steamlib.load_config()
        config["idler_auto_start"] = self.auto_start.get()
        steamlib.save_config(config)
        if self.auto_start.get():
            ready = [a for a in self.checked if a in self.rows]
            if not ready:
                ready = [a for a, row in self.rows.items() if row["drops"] > 0]
            if ready:
                self._start_many(ready, quiet=True)

    def _revive_crashed(self) -> None:
        """Restart jobs that died on their own, so a hiccup does not silently
        end an overnight run. Games that refuse Steamworks are left alone."""
        for app_id, job in list(self.jobs.items()):
            if not job.crashed or job.restarts >= 3:
                continue
            job.restarts += 1
            self._restarted += 1
            safety.log_error(f"idle job {app_id} died, restart {job.restarts}")
            self._start(app_id, quiet=True)

    def _recheck_drops(self, app_ids: list[int]) -> None:
        """Poll remaining drops for idling games and stop the finished ones."""
        client = get_web_client()
        if client is None or not client.logged_in:
            return

        def worker():
            updates = {}
            for app_id in app_ids:
                if self.rows.get(app_id, {}).get("drops", -1) < 0:
                    continue  # playtime-only target, nothing to watch
                try:
                    client._cache.pop(f"{client.profile_url}/gamecards/{app_id}/", None)
                    _, drops = client.card_set(app_id)
                    updates[app_id] = drops
                except Exception:
                    continue
            self.after(0, lambda: self._apply_drop_updates(updates))

        threading.Thread(target=worker, daemon=True).start()

    def _apply_drop_updates(self, updates: dict[int, int]) -> None:
        for app_id, drops in updates.items():
            if app_id in self.rows:
                self.rows[app_id]["drops"] = drops
            if drops == 0 and not self._limit_minutes():
                job = self.jobs.get(app_id)
                if job and job.alive:
                    job.stop()
        self._redraw()

    def stop_all_jobs(self) -> None:
        """Called when the whole app is closing -- terminate idle processes."""
        self._stop_all()
