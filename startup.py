"""Run-with-Windows support: drop a tiny launcher into the user's Startup
folder so ZFA opens on boot, straight to the system tray, and resumes idling.

A .vbs in Startup is the simplest reliable auto-start on Windows -- no admin,
no registry, easy to toggle by creating/deleting one file.
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
STARTUP_DIR = os.path.join(
    os.environ.get("APPDATA", ""),
    r"Microsoft\Windows\Start Menu\Programs\Startup",
)
LAUNCHER = os.path.join(STARTUP_DIR, "ZFA Achievement.vbs")


def _launch_command() -> str:
    """The command the Startup launcher runs, with --tray so it boots hidden."""
    if getattr(sys, "frozen", False):
        exe = sys.executable
        return f'"{exe}" --tray'
    # Source: use the windowless Python so no console flashes.
    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    if not os.path.isfile(pyw):
        pyw = sys.executable
    return f'"{pyw}" "{os.path.join(HERE, "main.py")}" --tray'


def is_enabled() -> bool:
    return os.path.isfile(LAUNCHER)


def enable() -> bool:
    """Create the Startup launcher. Returns True on success."""
    try:
        os.makedirs(STARTUP_DIR, exist_ok=True)
        script = (
            'Set sh = CreateObject("WScript.Shell")\n'
            f'sh.CurrentDirectory = "{HERE}"\n'
            f"sh.Run {_vbs_quote(_launch_command())}, 0, False\n"
        )
        with open(LAUNCHER, "w", encoding="utf-8") as handle:
            handle.write(script)
        return True
    except OSError:
        return False


def disable() -> bool:
    try:
        if os.path.isfile(LAUNCHER):
            os.remove(LAUNCHER)
        return True
    except OSError:
        return False


def _vbs_quote(command: str) -> str:
    """Quote a command string as a VBScript string literal."""
    return '"' + command.replace('"', '""') + '"'
