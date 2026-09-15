"""Build a Windows .exe with PyInstaller.

    python build_exe.py

Produces dist/SteamAchievementManager/SteamAchievementManager.exe. The one
.exe serves both the GUI and the per-game worker processes (see launcher.py).

Uses --onedir, not --onefile, on purpose: the app spawns many short-lived
worker processes (one per game for scanning, up to 20 at once for idling), and
a onefile build re-unpacks its whole payload on every launch -- seconds of
overhead per worker. Onedir unpacks once, so workers start almost instantly.
Distribute by zipping the dist/SteamAchievementManager folder.
"""

from __future__ import annotations

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
NAME = "SteamAchievementManager"

# Modules imported only via child processes / lazily -- name them so
# PyInstaller definitely bundles them.
HIDDEN = [
    "manager",
    "idle_worker",
    "scan_worker",
    "idlerwin",
    "badgeswin",
    "scanwin",
    "settings",
    "steamapi",
    "steamweb",
    "steamlib",
    "cookies",
    "backup",
    "safety",
    "i18n",
    "theme",
    "launcher",
    "tray",
    "singleton",
    "updater",
    "version",
    "PIL",
    "PIL.Image",
    "PIL.ImageTk",
    "Crypto.Cipher.AES",
    "win32crypt",
    "pystray",
    "pystray._win32",
    "websocket",
]


def main() -> int:
    import importlib.util

    if importlib.util.find_spec("PyInstaller") is None:
        print("Installing PyInstaller…", flush=True)
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "pyinstaller"], check=True
        )

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",  # workers start instantly; onefile re-unpacks every launch
        "--windowed",  # no console window for the GUI
        "--name",
        NAME,
    ]
    icon = os.path.join(HERE, "assets", "logo.ico")
    if os.path.isfile(icon):
        cmd += ["--icon", icon]
    assets = os.path.join(HERE, "assets")
    if os.path.isdir(assets):
        cmd += ["--add-data", f"{assets}{os.pathsep}assets"]
    for module in HIDDEN:
        cmd += ["--hidden-import", module]
    cmd.append(os.path.join(HERE, "main.py"))

    print("Running:", " ".join(cmd), flush=True)
    result = subprocess.run(cmd, cwd=HERE)
    if result.returncode == 0:
        exe = os.path.join(HERE, "dist", f"{NAME}.exe")
        print(f"\nDone: {exe}" if os.path.isfile(exe) else "\nBuild finished.")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
