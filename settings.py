"""Shared settings dialog: language, profile URL and the optional login cookie."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

import i18n
import steamlib
from i18n import n, t
import theme
from theme import BG, FG, FG_DIM


def get_web_client():
    """Build a SteamWeb from saved settings, or None when no profile is set."""
    from steamweb import SteamWeb

    config = steamlib.load_config()
    profile = config.get("profile_url", "").strip()
    if not profile:
        return None
    return SteamWeb(profile, config.get("cookie", ""))


def load_full_library(progress=None) -> list:
    """The widest game list we can build: local Steam records, plus the web
    library when a cookie is configured (catches games never launched here)."""
    games = {game.app_id: game for game in steamlib.all_owned_games(progress=progress)}

    client = get_web_client()
    if client is not None and client.logged_in:
        try:
            for app_id, name, hours in client.owned_games():
                existing = games.get(app_id)
                if existing is None:
                    games[app_id] = steamlib.Game(
                        app_id=app_id,
                        name=name,
                        installed=False,
                        playtime_minutes=int(hours * 60),
                    )
                elif existing.name.startswith("AppID "):
                    existing.name = name
        except Exception:
            pass  # the local list is still perfectly usable

    return sorted(games.values(), key=lambda game: game.name.lower())


class SettingsPage(tk.Frame):
    """Embedded settings page. `on_saved` runs after Save; `app` (optional)
    lets Save/Cancel navigate back to the games page."""

    def __init__(self, parent: tk.Misc, on_saved=None, app=None):
        super().__init__(parent, bg=BG, padx=18, pady=16)
        self.on_saved = on_saved
        self.app = app

        config = steamlib.load_config()
        self.profile_var = tk.StringVar(value=config.get("profile_url", ""))
        self.cookie_var = tk.StringVar(value=config.get("cookie", ""))
        self.language_var = tk.StringVar(value=i18n.LANGUAGES[i18n.get_language()])

        self._section(t("language"))
        row = tk.Frame(self, bg=BG)
        row.pack(fill="x", pady=(0, 4))
        combo = ttk.Combobox(
            row,
            textvariable=self.language_var,
            values=list(i18n.LANGUAGES.values()),
            state="readonly",
            width=18,
        )
        combo.pack(side="left")
        tk.Label(
            row,
            text=t("settings.language_note"),
            bg=BG,
            fg=FG_DIM,
            font=("Segoe UI", 8),
        ).pack(side="left", padx=10)
        tk.Frame(self, bg=BG, height=8).pack(fill="x")

        # Run with Windows (auto-start in the tray, resumes idling).
        import startup

        self.autostart_var = tk.BooleanVar(value=startup.is_enabled())
        theme.check(
            self, t("settings.autostart"), self.autostart_var, self._toggle_autostart
        ).pack(anchor="w")
        self.autostart_note = tk.Label(
            self, text="", bg=BG, fg=FG_DIM, anchor="w", font=("Segoe UI", 8)
        )
        self.autostart_note.pack(fill="x", pady=(0, 8))

        # Updates
        from version import APP_VERSION

        self._section(t("settings.updates"))
        tk.Label(
            self,
            text=t("settings.current_version", version=APP_VERSION),
            bg=BG,
            fg=FG_DIM,
            anchor="w",
            font=("Segoe UI", 8),
        ).pack(fill="x")
        theme.HoverButton(
            self, text=t("update.check"), command=self._check_updates,
            kind="secondary", padx=12, pady=6,
        ).pack(anchor="w", pady=(4, 10))

        self._section(t("settings.profile_url"), t("settings.profile_hint"))
        theme.entry(self, textvariable=self.profile_var, width=64).pack(
            fill="x", ipady=5, pady=(0, 12)
        )

        self._section(t("settings.cookie"), t("settings.cookie_help"))

        cookie_row = tk.Frame(self, bg=BG)
        cookie_row.pack(fill="x", pady=(0, 6))
        theme.entry(cookie_row, textvariable=self.cookie_var, show="*").pack(
            side="left", fill="x", expand=True, ipady=5
        )
        theme.HoverButton(
            cookie_row, text=t("settings.import_cookie"), command=self._import_cookie,
            kind="secondary", padx=10, pady=6,
        ).pack(side="left", padx=(6, 0))
        theme.HoverButton(
            cookie_row, text=t("settings.check_cookie"), command=self._check_cookie,
            kind="secondary", padx=10, pady=6,
        ).pack(side="left", padx=(6, 0))

        self.cookie_status = tk.Label(
            self, text="", bg=BG, fg=FG_DIM, anchor="w", font=theme.font(8)
        )
        self.cookie_status.pack(fill="x")

        tk.Label(
            self,
            text=t("settings.cookie_note"),
            bg=BG,
            fg=FG_DIM,
            anchor="w",
            font=theme.font(8),
        ).pack(fill="x", pady=(0, 12))

        buttons = tk.Frame(self, bg=BG)
        buttons.pack(fill="x")
        theme.HoverButton(
            buttons, text=t("btn.save"), command=self._save, kind="primary",
            padx=20, pady=8,
        ).pack(side="right")
        theme.HoverButton(
            buttons, text=t("btn.cancel"), command=self._cancel, kind="ghost",
            padx=14, pady=8,
        ).pack(side="right", padx=(0, 8))

    def _cancel(self) -> None:
        if self.app is not None:
            self.app.show_page("games")

    def _check_updates(self) -> None:
        if self.app is not None:
            self.app._check_updates(manual=True)

    def _toggle_autostart(self) -> None:
        import startup

        if self.autostart_var.get():
            ok = startup.enable()
            self.autostart_var.set(ok and startup.is_enabled())
            self.autostart_note.configure(
                text=t("settings.autostart_on") if ok else "", fg="#7ee787"
            )
        else:
            startup.disable()
            self.autostart_var.set(startup.is_enabled())
            self.autostart_note.configure(text=t("settings.autostart_off"), fg=FG_DIM)

    def _import_cookie(self) -> None:
        import threading

        import cookies

        config = steamlib.load_config()
        expected = ""
        profile = config.get("profile_url", "")
        if "/profiles/" in profile:
            expected = profile.rstrip("/").rsplit("/", 1)[-1]

        self.cookie_status.configure(text=t("settings.cookie_checking"), fg=FG_DIM)

        def worker():
            # 1) fast path: readable browsers (old Chrome / Edge / Firefox …)
            result = cookies.import_cookie(expected)
            # 2) fallback: let Chrome itself decrypt via CDP. Covers v20
            #    App-Bound Chrome and cases the static scan missed.
            if not result.cookie and cookies._find_chrome():
                self.after(0, lambda: self.cookie_status.configure(
                    text=t("settings.import_deep"), fg=FG_DIM))
                deep = cookies.import_via_cdp(expected)
                if deep.cookie:
                    result = deep
            self.after(0, lambda: self._import_done(result))

        threading.Thread(target=worker, daemon=True).start()

    def _import_done(self, result) -> None:
        if not self.winfo_exists():
            return
        if result.cookie:
            self.cookie_var.set(result.cookie)
            self.cookie_status.configure(
                text=t("settings.import_ok", browser=result.browser), fg="#7ee787"
            )
            self._check_cookie()
        elif result.app_bound:
            self.cookie_status.configure(
                text=t("settings.import_appbound", browser=result.browser), fg="#ffd479"
            )
        else:
            self.cookie_status.configure(text=t("settings.import_none"), fg="#ffd479")

    def _check_cookie(self) -> None:
        import threading

        from steamweb import SteamWeb

        cookie = self.cookie_var.get().strip()
        if not cookie:
            self.cookie_status.configure(text="", fg=FG_DIM)
            return
        profile = self.profile_var.get().strip().rstrip("/")
        if not profile:
            config = steamlib.load_config()
            profile = config.get("profile_url", "")
        if not profile:
            return

        self.cookie_status.configure(text=t("settings.cookie_checking"), fg=FG_DIM)

        def worker():
            try:
                steam_id = SteamWeb(profile, cookie).validate_login()
            except Exception:
                steam_id = ""
            self.after(0, lambda: self._show_check(steam_id))

        threading.Thread(target=worker, daemon=True).start()

    def _show_check(self, steam_id: str) -> None:
        if not self.winfo_exists():
            return
        config = steamlib.load_config()
        expected = ""
        if "/profiles/" in config.get("profile_url", ""):
            expected = config["profile_url"].rstrip("/").rsplit("/", 1)[-1]

        if not steam_id:
            self.cookie_status.configure(text=t("settings.cookie_invalid"), fg="#ff7b72")
        elif expected and steam_id != expected:
            self.cookie_status.configure(
                text=t("settings.cookie_wrong_account", id=steam_id), fg="#ffd479"
            )
        else:
            persona = config.get("persona", steam_id)
            self.cookie_status.configure(
                text=t("settings.cookie_valid", persona=persona), fg="#7ee787"
            )

    def _section(self, title: str, hint: str = "") -> None:
        tk.Label(
            self, text=title, bg=BG, fg=FG, anchor="w", font=("Segoe UI", 10, "bold")
        ).pack(fill="x")
        if hint:
            tk.Label(
                self,
                text=hint,
                bg=BG,
                fg=FG_DIM,
                anchor="w",
                justify="left",
                font=("Segoe UI", 8),
            ).pack(fill="x", pady=(0, 4))

    def _save(self) -> None:
        profile = self.profile_var.get().strip().rstrip("/")
        if profile and "steamcommunity.com" not in profile:
            messagebox.showerror(
                n("settings.bad_url_title"), n("settings.bad_url"), parent=self
            )
            return

        for code, label in i18n.LANGUAGES.items():
            if label == self.language_var.get():
                i18n.set_language(code)
                break

        config = steamlib.load_config()
        config["profile_url"] = profile
        config["cookie"] = self.cookie_var.get().strip()
        steamlib.save_config(config)
        if self.on_saved:
            self.on_saved()
