"""Auto-update from GitHub Releases.

On launch the app asks GitHub for the latest release; if its tag is newer than
the bundled version, the user is offered a one-click update. For the frozen
(.exe) build the new ZIP is downloaded, extracted, and swapped in by a tiny
batch file that waits for the app to close, replaces the install folder, and
relaunches. Running from source, "update" just opens the download page (source
is not replaced by a release ZIP).

Only stdlib is used, so there is nothing extra to bundle.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass

REPO = "abuzoz/ZFA-Achievement"
API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
ASSET_NAME = "ZFA-Achievement.zip"
INNER_DIR = "SteamAchievementManager"  # top folder inside the ZIP; exe basename

FROZEN = getattr(sys, "frozen", False)

CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008


@dataclass
class Update:
    version: str  # e.g. "1.2" (no leading v)
    url: str      # asset download URL
    notes: str    # release body / changelog
    page: str     # release html page


def _parse(v: str) -> tuple[int, ...]:
    v = v.strip().lstrip("vV")
    parts = []
    for chunk in v.split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts) or (0,)


def is_newer(remote: str, local: str) -> bool:
    """True if `remote` is a strictly higher version than `local`
    (1.2 > 1.1, and 1.1.0 == 1.1 -> not newer)."""
    ra, la = list(_parse(remote)), list(_parse(local))
    width = max(len(ra), len(la))
    ra += [0] * (width - len(ra))
    la += [0] * (width - len(la))
    return ra > la


def check() -> Update | None:
    """Return an Update if the latest release is newer than us, else None.
    Any network/parse error returns None (offline is not an error)."""
    from version import APP_VERSION

    req = urllib.request.Request(
        API_LATEST,
        headers={
            "User-Agent": "ZFA-Achievement-Updater",
            "Accept": "application/vnd.github+json",
        },
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.load(resp)

    tag = data.get("tag_name", "")
    if not tag or not is_newer(tag, APP_VERSION):
        return None

    url = ""
    for asset in data.get("assets", []):
        if asset.get("name") == ASSET_NAME:
            url = asset.get("browser_download_url", "")
            break
    if not url:
        return None

    return Update(
        version=tag.lstrip("vV"),
        url=url,
        notes=(data.get("body") or "").strip(),
        page=data.get("html_url", f"https://github.com/{REPO}/releases/latest"),
    )


def download(url: str, on_progress=None) -> str:
    """Download the update ZIP to a temp file; return its path.
    `on_progress(done, total)` is called as bytes arrive (total may be 0)."""
    fd, path = tempfile.mkstemp(suffix=".zip", prefix="zfa_update_")
    os.close(fd)
    req = urllib.request.Request(url, headers={"User-Agent": "ZFA-Achievement-Updater"})
    with urllib.request.urlopen(req, timeout=120) as resp, open(path, "wb") as out:
        total = int(resp.headers.get("Content-Length", 0) or 0)
        done = 0
        while True:
            chunk = resp.read(262144)
            if not chunk:
                break
            out.write(chunk)
            done += len(chunk)
            if on_progress:
                try:
                    on_progress(done, total)
                except Exception:
                    pass
    return path


def _build_swap_batch(new_dir: str, install_dir: str, exe: str, cleanup: list[str]) -> str:
    """Batch that waits for the app to exit, mirrors the new files in, relaunches,
    and deletes the temp files (and itself)."""
    dels = "\n".join(f'del /q "{p}" >nul 2>&1' for p in cleanup if os.path.isfile(p))
    rmdirs = "\n".join(
        f'rmdir /s /q "{p}" >nul 2>&1' for p in cleanup if os.path.isdir(p)
    )
    return f"""@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
set /a tries=0
:wait
tasklist /fi "imagename eq {INNER_DIR}.exe" | find /i "{INNER_DIR}.exe" >nul
if not errorlevel 1 (
    set /a tries+=1
    if !tries! lss 90 (
        timeout /t 1 /nobreak >nul
        goto wait
    )
)
robocopy "{new_dir}" "{install_dir}" /E /R:4 /W:1 /NFL /NDL /NJH /NJS /NP >nul
start "" "{exe}"
{rmdirs}
{dels}
del /q "%~f0" >nul 2>&1
"""


def apply_and_restart(zip_path: str) -> None:
    """Frozen builds only: extract the ZIP and hand off to a detached batch that
    replaces the install folder once this process exits, then relaunches."""
    tmp = tempfile.mkdtemp(prefix="zfa_new_")
    with zipfile.ZipFile(zip_path) as archive:
        archive.extractall(tmp)

    new_dir = os.path.join(tmp, INNER_DIR)
    if not os.path.isdir(new_dir):
        new_dir = tmp  # ZIP without the top folder

    exe = sys.executable
    install_dir = os.path.dirname(exe)

    bat = os.path.join(tempfile.gettempdir(), "zfa_update.bat")
    with open(bat, "w", encoding="utf-8") as handle:
        handle.write(_build_swap_batch(new_dir, install_dir, exe, [tmp, zip_path]))

    subprocess.Popen(
        ["cmd", "/c", bat],
        creationflags=CREATE_NO_WINDOW | DETACHED_PROCESS,
        close_fds=True,
    )
