"""Game picker. Pick a game, and it opens the achievement manager for it in a
fresh process (Steamworks allows exactly one AppID per process)."""

from __future__ import annotations

import os
import subprocess
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import safety
import steamlib
from badgeswin import BadgesPage
import i18n
from i18n import n, shape, t
from idlerwin import IdlerPage
from launcher import child_command
from scanwin import ScanPage
from settings import SettingsPage, load_full_library
import theme
from theme import (
    BG, BG_ALT, SURFACE, SIDEBAR, GRAD_A, GRAD_B,
    FG, FG_DIM, FG_FAINT, apply_theme,
)

HERE = os.path.dirname(os.path.abspath(__file__))
# When frozen, PyInstaller unpacks bundled data under sys._MEIPASS.
import sys as _sys

_ASSET_BASE = getattr(_sys, "_MEIPASS", HERE)
ASSETS = os.path.join(_ASSET_BASE, "assets")


def _asset(name: str) -> str:
    return os.path.join(ASSETS, name)


class Tooltip:
    """Tiny hover tooltip for the icon-only sidebar buttons."""

    def __init__(self, widget, text: str):
        self.widget = widget
        self.text = text
        self.tip = None
        widget.bind("<Enter>", self._show, add="+")
        widget.bind("<Leave>", self._hide, add="+")

    def _show(self, _):
        if self.tip or not self.text:
            return
        x = self.widget.winfo_rootx() + self.widget.winfo_width() + 6
        y = self.widget.winfo_rooty() + 6
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry(f"+{x}+{y}")
        tk.Label(
            self.tip, text=self.text, bg=SURFACE, fg=FG, font=theme.font(9),
            padx=8, pady=4, relief="flat",
        ).pack()

    def _hide(self, _):
        if self.tip:
            self.tip.destroy()
            self.tip = None


class PickerWindow(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(n("app.title"))
        self.geometry("1000x820")
        self.minsize(820, 680)
        self.configure(bg=BG)
        apply_theme(self)
        self._load_branding()
        self._tray = None
        self._tray_notified = False
        self._singleton_lock = None
        self._pending_update = None
        self._update_checked = False

        self.games: list[steamlib.Game] = []
        self.config_data = steamlib.load_config()
        self.dll_path = self.config_data.get("dll_path", "")

        safety.install(self)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._build_ui()  # builds the games page, which sets the dll label
        self._reload_games()
        self.after(200, self._autoconfigure)
        # Launched at boot (--tray): resume idling and hide to the tray.
        if "--tray" in _sys.argv:
            self.after(600, self._start_in_tray)
        self.after(1800, self._check_updates)  # look for a newer release

    def _start_in_tray(self) -> None:
        # Create the idler page so it loads and auto-resumes farming, even
        # though we never show it, then minimize straight to the tray.
        if "idler" not in self.pages:
            self.pages["idler"] = self._create_page("idler")
        self._on_close()

    def _on_close(self) -> None:
        """Closing the window hides it to the system tray (near the clock)
        instead of quitting, so the idler keeps running. Quit from the tray
        menu to actually exit."""
        if self._tray is None:
            import tray as tray_mod

            self._tray = tray_mod.Tray(
                self, _asset("logo.png"), n("app.title"),
                n("tray.show"), n("tray.quit"),
            )
        if self._tray.start():
            self.withdraw()  # remove from screen + taskbar; only the tray icon
            if not self._tray_notified:
                self._tray_notified = True
                self._tray.notify(n("tray.minimized"))
            return
        # No tray available -> fall back to a normal quit.
        self.quit_app()

    def restore_from_tray(self) -> None:
        self.deiconify()
        self.lift()
        self.focus_force()
        self.state("normal")
        # An update found while hidden in the tray is offered now that we're up.
        if self._pending_update is not None:
            info, self._pending_update = self._pending_update, None
            self.after(500, lambda: self._show_update_dialog(info))

    # -- single-instance ------------------------------------------------

    def attach_singleton(self, lock) -> None:
        """Keep the single-instance lock alive and surface the window when a
        second launch pings us. The ping arrives on a background socket thread,
        which only sets a thread-safe flag; the GUI thread polls it (Tkinter
        must not be touched from another thread)."""
        import singleton
        import threading

        self._singleton_lock = lock
        self._surface_flag = threading.Event()
        singleton.serve(lock, self._surface_flag.set)
        self._poll_surface()

    def _poll_surface(self) -> None:
        if not self.winfo_exists():
            return
        if self._surface_flag.is_set():
            self._surface_flag.clear()
            self._surface()
        self.after(250, self._poll_surface)

    def _surface(self) -> None:
        # A later launch asked us to show ourselves (we may be in the tray).
        self.restore_from_tray()

    # -- auto-update ----------------------------------------------------

    def _check_updates(self, manual: bool = False) -> None:
        """Ask GitHub (off the UI thread) whether a newer release exists."""
        if self._update_checked and not manual:
            return
        self._update_checked = True
        import updater

        def worker():
            try:
                info = updater.check()
                error = None
            except Exception as exc:  # offline / API error
                info, error = None, exc
            self.after(0, lambda: self._update_result(info, error, manual))

        threading.Thread(target=worker, daemon=True).start()

    def _update_result(self, info, error, manual: bool) -> None:
        if not self.winfo_exists():
            return
        if info is None:
            if manual:
                from version import APP_VERSION

                if error is not None:
                    messagebox.showwarning(
                        n("update.title"), n("update.check_failed"), parent=self
                    )
                else:
                    messagebox.showinfo(
                        n("update.title"),
                        n("update.uptodate", version=APP_VERSION),
                        parent=self,
                    )
            return

        # Respect a version the user chose to skip (auto-checks only).
        cfg = steamlib.load_config()
        if not manual and cfg.get("skip_update_version") == info.version:
            return

        # If we're hidden in the tray, defer the dialog until the user opens up.
        if not manual and not self.winfo_viewable():
            self._pending_update = info
            if self._tray is not None:
                try:
                    self._tray.notify(n("update.available_tray"))
                except Exception:
                    pass
            return

        self._show_update_dialog(info)

    def _show_update_dialog(self, info) -> None:
        if not self.winfo_exists():
            return
        from version import APP_VERSION
        import updater

        dlg = tk.Toplevel(self)
        dlg.title(n("update.title"))
        dlg.configure(bg=BG)
        dlg.transient(self)
        dlg.resizable(False, False)
        try:
            if self.logo_img is not None:
                dlg.iconphoto(False, self.logo_img)
        except Exception:
            pass

        pad = tk.Frame(dlg, bg=BG, padx=22, pady=18)
        pad.pack(fill="both", expand=True)

        tk.Label(
            pad, text="✨  " + n("update.title"), bg=BG, fg=FG,
            font=("Segoe UI", 13, "bold"), anchor="w",
        ).pack(fill="x")
        tk.Label(
            pad, text=n("update.body", version=info.version, current=APP_VERSION),
            bg=BG, fg=FG_DIM, justify="left", anchor="w", font=("Segoe UI", 10),
        ).pack(fill="x", pady=(6, 10))

        if info.notes:
            box = tk.Text(
                pad, height=8, width=52, wrap="word", bd=0,
                bg=SURFACE, fg=FG, padx=10, pady=8, font=("Segoe UI", 9),
                relief="flat", highlightthickness=0,
            )
            box.insert("1.0", info.notes)
            box.configure(state="disabled")
            box.pack(fill="both", expand=True, pady=(0, 12))

        row = tk.Frame(pad, bg=BG)
        row.pack(fill="x")

        def close():
            if dlg.winfo_exists():
                dlg.destroy()

        def later():
            close()

        def skip():
            cfg = steamlib.load_config()
            cfg["skip_update_version"] = info.version
            steamlib.save_config(cfg)
            close()

        can_self = updater.FROZEN or updater.is_git_source()

        def do_update():
            close()
            if updater.FROZEN:
                self._run_update(info)
            elif updater.is_git_source():
                self._run_source_update(info)
            else:
                import webbrowser

                webbrowser.open(info.page)

        primary = n("update.now") if can_self else n("update.open_page")
        theme.HoverButton(
            row, text=primary, command=do_update, kind="primary", padx=18, pady=8
        ).pack(side="right")
        theme.HoverButton(
            row, text=n("update.later"), command=later, kind="ghost", padx=12, pady=8
        ).pack(side="right", padx=(0, 8))
        theme.HoverButton(
            row, text=n("update.skip"), command=skip, kind="ghost", padx=12, pady=8
        ).pack(side="left")

        dlg.update_idletasks()
        x = self.winfo_rootx() + (self.winfo_width() - dlg.winfo_width()) // 2
        y = self.winfo_rooty() + (self.winfo_height() - dlg.winfo_height()) // 3
        dlg.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        dlg.grab_set()

    def _run_source_update(self, info) -> None:
        """Source install: pull the latest code with git, then relaunch."""
        import updater

        prog = tk.Toplevel(self)
        prog.title(n("update.title"))
        prog.configure(bg=BG)
        prog.transient(self)
        prog.resizable(False, False)
        frame = tk.Frame(prog, bg=BG, padx=26, pady=22)
        frame.pack(fill="both", expand=True)
        status = tk.Label(
            frame, text=n("update.downloading"), bg=BG, fg=FG,
            font=("Segoe UI", 10), anchor="w",
        )
        status.pack(fill="x", pady=(0, 10))
        bar = ttk.Progressbar(frame, mode="indeterminate", length=320)
        bar.pack(fill="x")
        bar.start(12)
        prog.update_idletasks()
        x = self.winfo_rootx() + (self.winfo_width() - prog.winfo_width()) // 2
        y = self.winfo_rooty() + (self.winfo_height() - prog.winfo_height()) // 3
        prog.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        prog.grab_set()

        def worker():
            try:
                updater.apply_source_update()
                ok, err = True, None
            except Exception as exc:
                ok, err = False, exc
            self.after(0, lambda: done(ok, err))

        def done(ok, err):
            if not ok:
                if prog.winfo_exists():
                    prog.destroy()
                messagebox.showerror(
                    n("update.title"), n("update.failed", error=err), parent=self
                )
                return
            if prog.winfo_exists():
                status.configure(text=n("update.installing"))
                prog.update_idletasks()
            updater.relaunch_source()
            self.after(400, self.quit_app)

        threading.Thread(target=worker, daemon=True).start()

    def _run_update(self, info) -> None:
        """Download the release ZIP with a progress dialog, then hand off to the
        swap batch and quit so it can replace the running files."""
        import updater

        if not info.url:  # release without a build attached -> just open the page
            import webbrowser

            webbrowser.open(info.page)
            return

        prog = tk.Toplevel(self)
        prog.title(n("update.title"))
        prog.configure(bg=BG)
        prog.transient(self)
        prog.resizable(False, False)
        frame = tk.Frame(prog, bg=BG, padx=26, pady=22)
        frame.pack(fill="both", expand=True)
        status = tk.Label(
            frame, text=n("update.downloading"), bg=BG, fg=FG,
            font=("Segoe UI", 10), anchor="w",
        )
        status.pack(fill="x", pady=(0, 10))
        bar = ttk.Progressbar(frame, mode="determinate", length=320, maximum=100)
        bar.pack(fill="x")
        prog.update_idletasks()
        x = self.winfo_rootx() + (self.winfo_width() - prog.winfo_width()) // 2
        y = self.winfo_rooty() + (self.winfo_height() - prog.winfo_height()) // 3
        prog.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        prog.grab_set()

        def on_progress(done, total):
            if total:
                self.after(0, lambda: bar.configure(value=done * 100 / total))

        def worker():
            try:
                zip_path = updater.download(info.url, on_progress)
            except Exception as exc:
                self.after(0, lambda error=exc: fail(error))
                return
            self.after(0, lambda: finish(zip_path))

        def fail(error):
            if prog.winfo_exists():
                prog.destroy()
            messagebox.showerror(
                n("update.title"), n("update.failed", error=error), parent=self
            )

        def finish(zip_path):
            if prog.winfo_exists():
                status.configure(text=n("update.installing"))
                bar.configure(value=100)
                prog.update_idletasks()
            try:
                updater.apply_and_restart(zip_path)
            except Exception as exc:
                fail(exc)
                return
            self.after(400, self.quit_app)  # let the swap batch take over

        threading.Thread(target=worker, daemon=True).start()

    def quit_app(self) -> None:
        idler = self.pages.get("idler")
        if idler is not None:
            idler.stop_all_jobs()
        if self._tray is not None:
            self._tray.stop()
        lock = getattr(self, "_singleton_lock", None)
        if lock is not None:
            try:
                lock.close()
            except OSError:
                pass
        self.destroy()

    def _load_branding(self) -> None:
        """Window/taskbar icon + the sidebar logo image, if Pillow + assets
        are present. Falls back silently to no icon / an emoji."""
        self.logo_img = None
        try:
            from PIL import Image, ImageTk

            ico = _asset("logo.ico")
            if os.path.isfile(ico):
                self.iconbitmap(ico)
            png = _asset("logo_64.png")
            if os.path.isfile(png):
                self._logo_src = Image.open(png).resize((44, 44), Image.LANCZOS)
                self.logo_img = ImageTk.PhotoImage(self._logo_src)
                self.iconphoto(True, self.logo_img)
        except Exception as exc:
            safety.log_error("branding", exc)

    # ------------------------------------------------------------------- ui

    def _build_ui(self) -> None:
        # =============================================================
        #  A thin frame around everything is the glowing "rim"; the app
        #  content lives inside it.  Layout: [ sidebar rail ] [ main ]
        # =============================================================
        # Thicker rim + a dark→bright pulse so the "breathing" is obvious.
        rim_dim = theme.mix(theme.ACCENT, BG, 0.45)
        self.configure(bg=rim_dim)
        shell = tk.Frame(self, bg=BG)
        shell.pack(fill="both", expand=True, padx=5, pady=5)
        self._glow_border = theme.BreathingBorder(
            self, rim_dim, theme.ACCENT_HI, period_ms=2200
        )

        self._build_sidebar(shell)

        main = tk.Frame(shell, bg=BG)
        main.pack(side="left", fill="both", expand=True)

        self._build_header(main)
        self._build_global_footer(main)  # copyright, pinned to the bottom

        # Swappable page area. The sidebar switches which page shows here;
        # pages are created lazily and kept alive (so idle jobs persist).
        self.content = tk.Frame(main, bg=BG)
        self.content.pack(fill="both", expand=True)
        self.pages: dict[str, tk.Frame] = {}
        self._current_page = None
        self._lang_at_build = i18n.get_language()
        self.show_page("games")

    # -- sidebar --------------------------------------------------------

    RAIL_W = 76

    def _build_sidebar(self, parent) -> None:
        # A canvas rail so a mouse-follow glow can sit behind the icons.
        rail = tk.Canvas(
            parent, width=self.RAIL_W, bg=SIDEBAR, highlightthickness=0, bd=0
        )
        rail.pack(side="left", fill="y")
        self._rail = rail

        self._rail_glow_img = None
        glow = theme.radial_glow(150, "#ffffff", max_alpha=60)
        if glow is not None:
            from PIL import ImageTk

            self._rail_glow_img = ImageTk.PhotoImage(glow)
            self._rail_glow_item = rail.create_image(
                self.RAIL_W // 2, -999, image=self._rail_glow_img, tags="rglow"
            )
            rail.bind("<Motion>", lambda e: self._move_rail_glow(e.y))
            rail.bind("<Leave>", lambda _: self._move_rail_glow(-999))

        # Logo doubles as the "home" (games) button.
        if self.logo_img is not None:
            logo = rail.create_image(self.RAIL_W // 2, 38, image=self.logo_img)
        else:
            logo = rail.create_text(
                self.RAIL_W // 2, 34, text="🎮", fill=FG, font=theme.font(20)
            )
        rail.tag_bind(logo, "<Button-1>", lambda _: self.show_page("games"))
        rail.tag_bind(logo, "<Enter>", lambda _: rail.configure(cursor="hand2"))
        rail.tag_bind(logo, "<Leave>", lambda _: rail.configure(cursor=""))

        # page name -> canvas text item, for active-state highlighting.
        self._nav_items: dict[str, int] = {}
        y = 100
        for icon, key, page in (
            ("📊", "picker.scan_button", "scan"),
            ("🏅", "picker.badges_button", "badges"),
            ("⏳", "picker.idler_button", "idler"),
            ("⚙", "picker.settings_button", "settings"),
        ):
            self._sidebar_icon(rail, icon, n(key), page, y)
            y += 56

    def _sidebar_icon(self, rail, icon, tooltip, page, y) -> None:
        item = rail.create_text(
            self.RAIL_W // 2, y, text=icon, fill=FG_DIM, font=theme.font(17),
        )
        self._nav_items[page] = item
        hit = rail.create_rectangle(
            self.RAIL_W // 2 - 22, y - 20, self.RAIL_W // 2 + 22, y + 20,
            outline="", fill="",
        )
        for tag in (hit, item):
            rail.tag_bind(tag, "<Button-1>", lambda _, p=page: self.show_page(p))
            rail.tag_bind(tag, "<Enter>", lambda _, i=item: (
                rail.itemconfigure(i, fill=FG), rail.configure(cursor="hand2")))
            rail.tag_bind(tag, "<Leave>", lambda _, i=item, p=page: (
                rail.itemconfigure(
                    i, fill=theme.ACCENT_HI if p == self._current_page else FG_DIM),
                rail.configure(cursor="")))

    def _highlight_sidebar(self, page: str) -> None:
        for name, item in getattr(self, "_nav_items", {}).items():
            self._rail.itemconfigure(
                item, fill=theme.ACCENT_HI if name == page else FG_DIM
            )

    # -- page switching -------------------------------------------------

    def show_page(self, name: str) -> None:
        """Swap the content area to the named page (created lazily, kept
        alive). All features live inside this one window."""
        if name == self._current_page:
            return
        current = self.pages.get(self._current_page)
        if current is not None:
            if hasattr(current, "on_hide"):
                current.on_hide()
            current.pack_forget()

        page = self.pages.get(name)
        if page is None:
            page = self._create_page(name)
            self.pages[name] = page
        page.pack(fill="both", expand=True)

        self._current_page = name
        self._highlight_sidebar(name)
        self._paint_header()

    def _create_page(self, name: str) -> tk.Frame:
        if name == "games":
            frame = tk.Frame(self.content, bg=BG, padx=18, pady=16)
            self._build_games_page(frame)
            return frame
        if name == "scan":
            return ScanPage(self.content, self.dll_path, app=self)
        if name == "badges":
            return BadgesPage(self.content, app=self)
        if name == "idler":
            return IdlerPage(self.content, self.dll_path, app=self)
        if name == "settings":
            return SettingsPage(self.content, on_saved=self._on_settings_saved, app=self)
        raise ValueError(name)

    def _build_games_page(self, parent) -> None:
        self._build_stats(parent)
        self._build_controls(parent)
        self._build_games_footer(parent)  # bottom actions
        self._build_table(parent)         # fills the remaining space

    def _on_settings_saved(self) -> None:
        self.config_data = steamlib.load_config()
        if i18n.get_language() != self._lang_at_build:
            self._rebuild()  # language changed: rebuild everything
            return
        self._show_account()
        # Drop the cached games page so profile/cookie changes take effect.
        old = self.pages.pop("games", None)
        if old is not None:
            old.destroy()
        self.show_page("games")
        self._reload_games()

    def _move_rail_glow(self, y) -> None:
        if self._rail_glow_img is None:
            return
        self._rail.coords(self._rail_glow_item, self.RAIL_W // 2, y)
        self._rail.tag_lower("rglow")  # keep icons on top

    # -- gradient header -----------------------------------------------

    HEADER_H = 84

    def _build_header(self, parent) -> None:
        self.header = tk.Canvas(
            parent, height=self.HEADER_H, highlightthickness=0, bd=0, bg=BG
        )
        self.header.pack(fill="x")

        # Mouse-follow spotlight: a soft glow image that tracks the cursor
        # across the header banner. Needs Pillow. Set before binding Configure
        # so an early resize event never hits an undefined attribute.
        self._glow_img = None
        self.header.bind("<Configure>", self._paint_header)
        glow = theme.radial_glow(260, "#ffffff", max_alpha=125)
        if glow is not None:
            from PIL import ImageTk

            self._glow_img = ImageTk.PhotoImage(glow)
            self._glow_item = self.header.create_image(
                -999, self.HEADER_H // 2, image=self._glow_img, tags="glow"
            )
            self.header.bind("<Motion>", self._move_glow)
            self.header.bind("<Leave>", lambda _: self.header.coords(
                self._glow_item, -999, self.HEADER_H // 2))

        # Language toggle lives on the header, embedded via a canvas window.
        other = "English" if i18n.get_language() == "ar" else "العربية"
        self._lang_btn = theme.RoundedButton(
            self.header, text=f"🌐  {other}", command=self._toggle_language,
            kind="secondary", width=118, height=34, radius=10, bg=GRAD_B,
        )
        self._lang_win = self.header.create_window(
            0, self.HEADER_H // 2, window=self._lang_btn, anchor="w"
        )

    def _move_glow(self, event) -> None:
        self.header.coords(self._glow_item, event.x, event.y)
        self.header.tag_raise("glow")
        self.header.tag_raise("txt")

    # Header title per page.
    _PAGE_TITLE = {
        "games": "picker.header",
        "scan": "scan.title",
        "badges": "badges.title",
        "idler": "idler.title",
        "settings": "settings.title",
    }

    def _paint_header(self, event=None) -> None:
        w = self.header.winfo_width()
        h = self.HEADER_H
        theme.gradient_h(self.header, w, h, GRAD_A, GRAD_B)
        self.header.delete("txt")
        title = t(self._PAGE_TITLE.get(self._current_page or "games", "picker.header"))
        self.header.create_text(
            24, h // 2 - 10, text=title, fill="#ffffff", anchor="w",
            font=theme.font(17, "bold"), tags="txt",
        )
        persona = self.config_data.get("persona", "")
        if persona:
            self.header.create_text(
                24, h // 2 + 14, text=persona, fill="#e8ddff", anchor="w",
                font=theme.font(9), tags="txt",
            )
        # Glow sits above the gradient, text above the glow.
        if self._glow_img is not None:
            self.header.tag_raise("glow")
        self.header.tag_raise("txt")
        # Keep the language button pinned to the right edge.
        self.header.coords(self._lang_win, max(140, w - 130), h // 2)

    # -- stat cards -----------------------------------------------------

    def _build_stats(self, parent) -> None:
        self.stats = tk.Frame(parent, bg=BG)
        self.stats.pack(fill="x", pady=(0, 14))
        self._render_stats()

    def _render_stats(self) -> None:
        if not getattr(self, "stats", None) or not self.stats.winfo_exists():
            return
        for child in self.stats.winfo_children():
            child.destroy()
        total = len(self.games)
        installed = sum(1 for g in self.games if getattr(g, "installed", True))
        avg = self._avg_completion()
        cards = [
            (str(total or "—"), n("picker.stat_games"), True),
            (str(installed), n("picker.stat_installed"), False),
            (avg, n("picker.stat_completion"), False),
        ]
        for value, caption, accent in cards:
            theme.StatCard(
                self.stats, value=value, caption=caption, accent=accent
            ).pack(side="left", padx=(0, 12))

    def _avg_completion(self) -> str:
        """Average unlocked-% across scanned games, from the scan cache."""
        try:
            import scanwin

            data = scanwin._load_cache()
        except Exception:
            data = {}
        pcts = [
            100 * e["unlocked"] / e["total"]
            for e in data.values()
            if e.get("total")
        ]
        return f"{round(sum(pcts) / len(pcts))}%" if pcts else "—"

    # -- search / scope controls ---------------------------------------

    def _build_controls(self, parent) -> None:
        bar = tk.Frame(parent, bg=BG)
        bar.pack(fill="x", pady=(0, 10))

        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self._refilter())
        tk.Label(bar, text="🔍", bg=BG, fg=FG_DIM, font=theme.font(11)).pack(side="left")
        theme.entry(bar, textvariable=self.search_var).pack(
            side="left", fill="x", expand=True, padx=(6, 12), ipady=6
        )

        self.show_all = tk.BooleanVar(
            value=bool(self.config_data.get("show_all_games", True))
        )
        theme.check(
            bar, t("picker.whole_library"), self.show_all, self._toggle_scope
        ).pack(side="left")

    # -- game table -----------------------------------------------------

    def _build_table(self, parent) -> None:
        body = tk.Frame(parent, bg=SURFACE)
        body.pack(fill="both", expand=True)

        self.tree = ttk.Treeview(
            body, columns=("appid", "name", "hours"), show="headings", selectmode="browse"
        )
        for key, text, width, anchor, stretch in (
            ("appid", t("col.appid"), 90, "w", False),
            ("name", t("col.game"), 360, "w", True),
            ("hours", t("picker.col_played"), 80, "e", False),
        ):
            self.tree.heading(key, text=text)
            self.tree.column(key, width=width, anchor=anchor, stretch=stretch)
        self.tree.tag_configure("notinstalled", foreground=FG_DIM)
        self.tree.tag_configure("odd", background=BG_ALT)
        scrollbar = ttk.Scrollbar(body, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True, padx=4, pady=4)
        self.tree.bind("<Double-1>", lambda _: self._open_selected())
        self.tree.bind("<Return>", lambda _: self._open_selected())

    # -- footers --------------------------------------------------------

    def _build_global_footer(self, parent) -> None:
        """Copyright line pinned to the very bottom of the window (all pages)."""
        from version import APP_VERSION

        brand = tk.Frame(parent, bg=BG_ALT)
        brand.pack(fill="x", side="bottom")
        tk.Label(
            brand, text=f"{n('app.copyright')}  ·  v{APP_VERSION}", bg=BG_ALT,
            fg=FG_FAINT, anchor="center", font=theme.font(8), pady=5,
        ).pack(fill="x")

    def _build_games_footer(self, parent) -> None:
        # Packed bottom-up inside the games page: path, actions, manual row.
        self.dll_label = tk.Label(
            parent, text="", bg=BG, fg=FG_FAINT, anchor="w", font=theme.font(8),
            pady=4,
        )
        self.dll_label.pack(fill="x", side="bottom")
        self._set_dll_label()

        footer = tk.Frame(parent, bg=BG, pady=12)
        footer.pack(fill="x", side="bottom")
        theme.RoundedButton(
            footer, text=t("picker.open_achievements"), command=self._open_selected,
            kind="primary", width=170, height=42, radius=12, bg=BG,
        ).pack(side="right")
        for key, command, w in (
            ("picker.refresh_games", self._reload_games, 120),
            ("picker.set_dll", self._browse_dll, 150),
        ):
            theme.RoundedButton(
                footer, text=t(key), command=command, kind="ghost",
                width=w, height=42, radius=12, bg=BG,
            ).pack(side="right", padx=(0, 8))

        manual = tk.Frame(parent, bg=BG)
        manual.pack(fill="x", side="bottom")
        tk.Label(manual, text=t("picker.open_by_appid"), bg=BG, fg=FG_DIM).pack(side="left")
        self.appid_var = tk.StringVar()
        theme.entry(manual, textvariable=self.appid_var, width=12).pack(
            side="left", padx=8, ipady=4
        )
        theme.RoundedButton(
            manual, text=t("picker.open"), command=self._open_manual,
            kind="secondary", width=80, height=32, radius=9, bg=BG,
        ).pack(side="left")

    def _toggle_language(self) -> None:
        i18n.set_language("en" if i18n.get_language() == "ar" else "ar")
        self._rebuild()

    def _rebuild(self) -> None:
        """Re-create every widget (e.g. after a language change)."""
        if getattr(self, "_glow_border", None) is not None:
            self._glow_border.stop()
        # Terminate any idle jobs before their page is destroyed.
        idler = self.pages.get("idler") if hasattr(self, "pages") else None
        if idler is not None:
            idler.stop_all_jobs()
        for child in self.winfo_children():
            child.destroy()
        self.title(n("app.title"))
        self._build_ui()

    def _set_dll_label(self) -> None:
        if self.dll_path:
            self.dll_label.configure(text=t("picker.dll_path", path=self.dll_path))
        else:
            self.dll_label.configure(text=t("picker.dll_missing"))

    # ----------------------------------------------------------------- data

    def _toggle_scope(self) -> None:
        self.config_data["show_all_games"] = self.show_all.get()
        steamlib.save_config(self.config_data)
        self._reload_games()

    def _reload_games(self) -> None:
        if not self.show_all.get():
            self.games = steamlib.installed_games()
            self._refilter()
            if not self.games:
                messagebox.showwarning(n("steam.title"), n("picker.no_games"))
            return

        # First run downloads names for games that were never installed here.
        self.dll_label.configure(text=t("picker.reading_library"))

        def worker():
            def progress(index, total):
                self.after(
                    0,
                    lambda: self.dll_label.configure(
                        text=t("picker.resolving_names", index=index, total=total)
                    ),
                )

            try:
                games = load_full_library(progress=progress)
            except Exception as exc:
                # `exc` is unbound after the except block; bind it as a default.
                self.after(0, lambda error=exc: self._scope_failed(error))
                return
            self.after(0, lambda: self._scope_loaded(games))

        threading.Thread(target=worker, daemon=True).start()

    def _scope_loaded(self, games) -> None:
        self.games = games
        self._refilter()
        self._set_dll_label()

    def _scope_failed(self, exc: Exception) -> None:
        self._set_dll_label()
        messagebox.showerror(n("steam.title"), n("picker.library_failed", error=exc))

    def _refilter(self) -> None:
        # The games page may have been rebuilt/destroyed while a load ran.
        if not getattr(self, "tree", None) or not self.tree.winfo_exists():
            return
        self._render_stats()  # totals depend on the current game list
        needle = self.search_var.get().strip().lower()
        self.tree.delete(*self.tree.get_children())
        row = 0
        for game in self.games:
            if needle and needle not in game.name.lower() and needle not in str(game.app_id):
                continue
            hours = game.playtime_minutes / 60
            tags = [] if game.installed else ["notinstalled"]
            if row % 2:
                tags.append("odd")  # subtle zebra striping
            self.tree.insert(
                "",
                "end",
                iid=str(game.app_id),
                values=(
                    game.app_id,
                    shape(
                        game.name
                        if game.installed
                        else f"{game.name}  ·  {n('picker.not_installed')}"
                    ),
                    f"{hours:.0f}h" if hours >= 1 else "",
                ),
                tags=tuple(tags),
            )
            row += 1

    def _autoconfigure(self) -> None:
        """Detect the Steam account and the DLL without asking the user.

        Runs on every start. Nothing here blocks or pops up: if something
        cannot be found the footer says so and the rest keeps working.
        """
        if self.dll_path and os.path.isfile(self.dll_path):
            self._show_account()
            return

        self.dll_label.configure(text=t("picker.setting_up"))

        def worker():
            try:
                config = steamlib.autoconfigure(
                    progress=lambda name: self.after(
                        0, lambda: self.dll_label.configure(text=t("picker.dll_searching"))
                    )
                )
            except Exception as exc:
                safety.log_error("autoconfigure", exc)
                config = steamlib.load_config()
            self.after(0, lambda: self._autoconfigured(config))

        threading.Thread(target=worker, daemon=True).start()

    def _autoconfigured(self, config: dict) -> None:
        self.config_data = config
        self.dll_path = config.get("dll_path", "")
        self._set_dll_label()
        self._show_account()

    def _show_account(self) -> None:
        # The persona is drawn straight onto the gradient header.
        self._paint_header()

    def _browse_dll(self) -> None:
        path = filedialog.askopenfilename(
            title=n("dll.select"),
            filetypes=[("steam_api64.dll", "steam_api64.dll"), ("DLL", "*.dll")],
        )
        if not path:
            return
        self.dll_path = path
        self.config_data["dll_path"] = path
        steamlib.save_config(self.config_data)
        self._set_dll_label()

    # --------------------------------------------------------------- launch

    def _open_selected(self) -> None:
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo(n("app.title"), n("picker.select_first"))
            return
        app_id = int(selection[0])
        name = next((g.name for g in self.games if g.app_id == app_id), f"AppID {app_id}")
        self._launch(app_id, name)

    def _open_manual(self) -> None:
        raw = self.appid_var.get().strip()
        if not raw.isdigit():
            messagebox.showerror(n("app.title"), n("picker.bad_appid"))
            return
        app_id = int(raw)
        name = next((g.name for g in self.games if g.app_id == app_id), f"AppID {app_id}")
        self._launch(app_id, name)

    def _launch(self, app_id: int, name: str) -> None:
        if not self.dll_path or not os.path.isfile(self.dll_path):
            messagebox.showerror(n("dll.title"), n("dll.required"))
            return

        # A separate process per game: Steamworks locks one AppID per process.
        environment = dict(os.environ, SteamAppId=str(app_id), SteamGameId=str(app_id))
        try:
            subprocess.Popen(
                child_command("manager", app_id, self.dll_path, name),
                env=environment,
                cwd=HERE,
            )
        except OSError as exc:
            messagebox.showerror(n("app.title"), n("picker.launch_failed", error=exc))


def _already_running_message() -> None:
    """Native, no-Tk-root notice that another instance is already open."""
    title = n("single.running_title")
    body = n("single.running_body")
    try:
        import ctypes

        MB_OK = 0x0
        MB_ICONINFORMATION = 0x40
        MB_SETFOREGROUND = 0x10000
        MB_TOPMOST = 0x40000
        ctypes.windll.user32.MessageBoxW(
            0, body, title, MB_OK | MB_ICONINFORMATION | MB_SETFOREGROUND | MB_TOPMOST
        )
    except Exception:
        print(body)


def main() -> int:
    import singleton

    # One GUI instance only. If the port is already held by *our* app, ask it
    # to surface its window (it may be hidden in the tray) and exit quietly.
    lock = singleton.acquire()
    if lock is None:
        if singleton.signal_existing():
            _already_running_message()
            return 0
        # Port held by something unrelated -> start anyway, without the lock.

    win = PickerWindow()
    if lock is not None:
        win.attach_singleton(lock)
    win.mainloop()
    return 0


if __name__ == "__main__":
    import launcher

    # When frozen, the same .exe re-launches itself as a worker process.
    launcher.dispatch()
    raise SystemExit(main())
