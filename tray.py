"""System-tray icon (near the clock). Closing the window hides it here instead
of quitting, so the idler keeps running in the background.

pystray runs its icon on its own thread; menu callbacks marshal back onto the
Tk main thread via `root.after`, which is the only thread-safe way to touch Tk.
"""

from __future__ import annotations

import os

import safety

try:
    import pystray
    from PIL import Image

    HAS_TRAY = True
except Exception:  # pystray or Pillow missing -> caller falls back to quitting
    HAS_TRAY = False


class Tray:
    def __init__(self, app, image_path: str, title: str, show_text: str, quit_text: str):
        self.app = app
        self.title = title
        self.icon = None
        self._image = None
        if HAS_TRAY and os.path.isfile(image_path):
            try:
                self._image = Image.open(image_path)
            except Exception as exc:
                safety.log_error("tray image", exc)

        self._show_text = show_text
        self._quit_text = quit_text

    @property
    def available(self) -> bool:
        return HAS_TRAY and self._image is not None

    def start(self) -> bool:
        """Create and run the tray icon on a background thread. Returns False
        if the tray is unavailable (caller should just quit normally)."""
        if not self.available:
            return False
        if self.icon is not None:
            return True
        menu = pystray.Menu(
            pystray.MenuItem(self._show_text, self._on_show, default=True),
            pystray.MenuItem(self._quit_text, self._on_quit),
        )
        self.icon = pystray.Icon("zfa", self._image, self.title, menu)
        try:
            self.icon.run_detached()
        except Exception as exc:
            safety.log_error("tray run", exc)
            self.icon = None
            return False
        return True

    def notify(self, message: str) -> None:
        if self.icon is not None:
            try:
                self.icon.notify(message, self.title)
            except Exception:
                pass  # notifications are best-effort

    def stop(self) -> None:
        if self.icon is not None:
            try:
                self.icon.stop()
            except Exception:
                pass
            self.icon = None

    # menu callbacks run on pystray's thread -> hop back to the Tk thread
    def _on_show(self, *_):
        self.app.after(0, self.app.restore_from_tray)

    def _on_quit(self, *_):
        self.app.after(0, self.app.quit_app)
