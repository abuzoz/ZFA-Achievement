"""Best-effort automatic import of the steamLoginSecure cookie from a browser.

Chrome 127+ encrypts cookies with App-Bound Encryption ("v20"), which is
designed to be unreadable outside the browser process -- so this cannot cover
every setup. It handles the schemes that *are* readable (Chrome/Edge/Brave/
Opera pre-127 "v10/v11", and Firefox's plaintext store) and reports clearly
when a browser cannot be read, so the UI can fall back to manual paste.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import sqlite3
import tempfile
import urllib.parse
from dataclasses import dataclass

LA = os.environ.get("LOCALAPPDATA", "")
AP = os.environ.get("APPDATA", "")

# Chromium browsers: name -> User Data root.
_CHROMIUM = {
    "Chrome": os.path.join(LA, r"Google\Chrome\User Data"),
    "Edge": os.path.join(LA, r"Microsoft\Edge\User Data"),
    "Brave": os.path.join(LA, r"BraveSoftware\Brave-Browser\User Data"),
    "Opera": os.path.join(AP, r"Opera Software\Opera Stable"),
    "Opera GX": os.path.join(AP, r"Opera Software\Opera GX Stable"),
    "Vivaldi": os.path.join(LA, r"Vivaldi\User Data"),
}
_FIREFOX = os.path.join(AP, r"Mozilla\Firefox\Profiles")


@dataclass
class CookieResult:
    cookie: str = ""
    browser: str = ""
    steam_id: str = ""
    # Why nothing usable came back, when cookie is empty.
    reason: str = ""
    app_bound: bool = False  # a v20 store was seen but could not be read


def steam_id_from_cookie(cookie: str) -> str:
    """steamLoginSecure is '<steamid>||<token>' (URL-encoded)."""
    value = urllib.parse.unquote(cookie)
    head = value.split("||", 1)[0].split("%7C", 1)[0]
    return head if head.isdigit() and head.startswith("7656") else ""


# ------------------------------------------------ deep import via Chrome/CDP
#
# Chrome 127+ "v20" App-Bound cookies can't be decrypted from outside Chrome.
# But Chrome itself can: run a headless Chrome on a *copy* of the profile with
# a remote-debugging port, then ask it for the (already-decrypted) cookie over
# the DevTools Protocol. This is the user clicking a button in their own app on
# their own machine -- the value only ever lands in the local config.

_CHROME_EXES = [
    os.path.join(os.environ.get("PROGRAMFILES", r"C:\Program Files"),
                 r"Google\Chrome\Application\chrome.exe"),
    os.path.join(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
                 r"Google\Chrome\Application\chrome.exe"),
    os.path.join(LA, r"Google\Chrome\Application\chrome.exe"),
]


def _find_chrome() -> str | None:
    return next((p for p in _CHROME_EXES if os.path.isfile(p)), None)


def _sqlite_backup(src: str, dst: str) -> bool:
    """Copy a possibly-locked SQLite DB (Chrome's Cookies) via the backup API."""
    try:
        source = sqlite3.connect(f"file:{src}?mode=ro&immutable=1", uri=True)
        target = sqlite3.connect(dst)
        with target:
            source.backup(target)
        source.close()
        target.close()
        return True
    except sqlite3.Error:
        return False


def _copy_chrome_profile(user_data: str, dst: str) -> None:
    os.makedirs(dst, exist_ok=True)
    ls = os.path.join(user_data, "Local State")
    if os.path.isfile(ls):
        try:
            shutil.copy2(ls, os.path.join(dst, "Local State"))
        except OSError:
            pass
    src_def = os.path.join(user_data, "Default")
    dst_def = os.path.join(dst, "Default")
    os.makedirs(os.path.join(dst_def, "Network"), exist_ok=True)

    # Cookies is locked while Chrome runs -> copy via SQLite backup.
    cookies_src = os.path.join(src_def, "Network", "Cookies")
    if os.path.isfile(cookies_src):
        cookies_dst = os.path.join(dst_def, "Network", "Cookies")
        if not _sqlite_backup(cookies_src, cookies_dst):
            try:
                shutil.copy2(cookies_src, cookies_dst)
            except OSError:
                pass

    for rel in ("Preferences", "Secure Preferences"):
        s = os.path.join(src_def, rel)
        if os.path.isfile(s):
            try:
                shutil.copy2(s, os.path.join(dst_def, rel))
            except OSError:
                pass


def import_via_cdp(expected_steam_id: str = "", port: int = 9222) -> CookieResult:
    """Deep import: let Chrome decrypt the cookie for us over CDP. Best-effort;
    returns a clear reason on failure so the UI can fall back to manual paste."""
    import subprocess
    import time
    import urllib.request

    try:
        import websocket  # websocket-client
    except ImportError:
        return CookieResult(reason="websocket-client not installed")

    chrome = _find_chrome()
    if chrome is None:
        return CookieResult(reason="Chrome not found")
    user_data = _CHROMIUM["Chrome"]
    if not os.path.isdir(user_data):
        return CookieResult(reason="no Chrome profile")

    tmp = tempfile.mkdtemp(prefix="zfa_chrome_")
    proc = None
    try:
        _copy_chrome_profile(user_data, tmp)
        proc = subprocess.Popen(
            [
                chrome, f"--user-data-dir={tmp}", "--headless=new",
                f"--remote-debugging-port={port}", "--no-first-run",
                "--no-default-browser-check", "--disable-gpu", "--disable-extensions",
            ],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

        ws_url = None
        for _ in range(40):
            time.sleep(0.5)
            try:
                data = json.loads(
                    urllib.request.urlopen(
                        f"http://127.0.0.1:{port}/json/version", timeout=3
                    ).read()
                )
                ws_url = data.get("webSocketDebuggerUrl")
                if ws_url:
                    break
            except Exception:
                continue
        if not ws_url:
            return CookieResult(reason="Chrome debug port unavailable")

        ws = websocket.create_connection(ws_url, timeout=15, max_size=None)
        try:
            ws.send(json.dumps({"id": 1, "method": "Storage.getCookies", "params": {}}))
            cookies = []
            for _ in range(15):
                msg = json.loads(ws.recv())
                if msg.get("id") == 1:
                    cookies = (msg.get("result") or {}).get("cookies", [])
                    break
        finally:
            ws.close()

        matches = [
            c for c in cookies
            if c.get("name") == "steamLoginSecure"
            and "steamcommunity.com" in c.get("domain", "")
        ] or [c for c in cookies if c.get("name") == "steamLoginSecure"]

        for c in matches:
            value = c.get("value", "")
            sid = steam_id_from_cookie(value)
            if sid and (not expected_steam_id or sid == expected_steam_id):
                return CookieResult(cookie=value, browser="Chrome (deep)", steam_id=sid)
        if matches:
            v = matches[0].get("value", "")
            return CookieResult(
                cookie=v, browser="Chrome (deep)", steam_id=steam_id_from_cookie(v)
            )
        return CookieResult(reason="no Steam cookie in Chrome")
    except Exception as exc:  # noqa: BLE001 - report any failure to the UI
        return CookieResult(reason=f"deep import failed: {exc}")
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except Exception:
                proc.kill()
            time.sleep(0.3)
        shutil.rmtree(tmp, ignore_errors=True)


def _copy(path: str) -> str | None:
    """Browsers keep the DB locked; work on a copy."""
    if not os.path.isfile(path):
        return None
    tmp = os.path.join(tempfile.gettempdir(), f"sam_{os.getpid()}_{os.path.basename(path)}")
    try:
        shutil.copy2(path, tmp)
        return tmp
    except OSError:
        return None


def _read_cookie_rows(db: str, where: str) -> list:
    """Read cookie rows even when the browser has the file open (Windows
    locks it). Reads immutable read-only first, then falls back to a copy."""
    if not os.path.isfile(db):
        return []
    query = f"SELECT host_key, name, encrypted_value FROM cookies WHERE {where}"
    # 1) immutable read-only URI: works while Chrome holds the file open.
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro&immutable=1", uri=True)
        rows = con.execute(query).fetchall()
        con.close()
        return rows
    except sqlite3.Error:
        pass
    # 2) fall back to a plain copy (works when the file is not locked).
    tmp = _copy(db)
    if not tmp:
        return []
    try:
        con = sqlite3.connect(tmp)
        rows = con.execute(query).fetchall()
        con.close()
        return rows
    except sqlite3.Error:
        return []
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


# --------------------------------------------------------------- chromium


def _chromium_master_key(base: str):
    state_path = os.path.join(base, "Local State")
    try:
        state = json.load(open(state_path, encoding="utf-8"))
        enc = base64.b64decode(state["os_crypt"]["encrypted_key"])
    except (OSError, ValueError, KeyError):
        return None
    if enc[:5] != b"DPAPI":
        return None
    try:
        import win32crypt

        return win32crypt.CryptUnprotectData(enc[5:], None, None, None, 0)[1]
    except Exception:
        return None


def _decrypt_chromium_value(blob: bytes, master_key) -> str:
    prefix = bytes(blob[:3])
    if prefix in (b"v10", b"v11") and master_key is not None:
        try:
            from Crypto.Cipher import AES

            iv, ct, tag = blob[3:15], blob[15:-16], blob[-16:]
            pt = AES.new(master_key, AES.MODE_GCM, iv).decrypt_and_verify(ct, tag)
            # Chrome 130+ prepends a 32-byte header to the plaintext.
            if len(pt) > 32 and not pt[:1].isascii():
                pt = pt[32:]
            return pt.decode("utf-8", "replace").strip()
        except Exception:
            return ""
    if prefix == b"v20":
        return ""  # App-Bound: unreadable outside the browser
    # Legacy DPAPI-only value (very old Chrome).
    try:
        import win32crypt

        return win32crypt.CryptUnprotectData(blob, None, None, None, 0)[1].decode(
            "utf-8", "replace"
        )
    except Exception:
        return ""


def _read_chromium(name: str, base: str) -> CookieResult:
    if not os.path.isdir(base):
        return CookieResult(reason="not installed")

    master_key = _chromium_master_key(base)
    saw_app_bound = False

    # Profiles: Default, Profile 1, Profile 2, …
    profiles = ["Default"] + [
        d for d in os.listdir(base) if d.startswith("Profile ")
    ] if os.path.isdir(base) else ["Default"]

    for profile in profiles:
        for rel in (("Network", "Cookies"), ("Cookies",)):
            db = os.path.join(base, profile, *rel)
            rows = _read_cookie_rows(
                db,
                "host_key LIKE '%steamcommunity.com' AND name='steamLoginSecure'",
            )
            for host, cname, blob in rows:
                if bytes(blob[:3]) == b"v20":
                    saw_app_bound = True
                value = _decrypt_chromium_value(bytes(blob), master_key)
                steam_id = steam_id_from_cookie(value)
                if steam_id:
                    return CookieResult(
                        cookie=value, browser=name, steam_id=steam_id
                    )

    if saw_app_bound:
        return CookieResult(
            browser=name, app_bound=True, reason="app-bound (Chrome 127+)"
        )
    return CookieResult(reason="no Steam cookie")


# ---------------------------------------------------------------- firefox


def _read_firefox() -> CookieResult:
    if not os.path.isdir(_FIREFOX):
        return CookieResult(reason="not installed")
    for profile in os.listdir(_FIREFOX):
        db = os.path.join(_FIREFOX, profile, "cookies.sqlite")
        tmp = _copy(db)
        if not tmp:
            continue
        try:
            con = sqlite3.connect(tmp)
            row = con.execute(
                "SELECT value FROM moz_cookies "
                "WHERE host LIKE '%steamcommunity.com' AND name='steamLoginSecure'"
            ).fetchone()
            con.close()
        except sqlite3.Error:
            row = None
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass
        if row and steam_id_from_cookie(row[0]):
            return CookieResult(
                cookie=row[0].strip(), browser="Firefox",
                steam_id=steam_id_from_cookie(row[0]),
            )
    return CookieResult(reason="no Steam cookie")


# ------------------------------------------------------------------ public


def import_cookie(expected_steam_id: str = "") -> CookieResult:
    """Scan every known browser and return the first usable Steam cookie.

    If expected_steam_id is given, a cookie for a different account is skipped
    so we never grab the wrong login.
    """
    app_bound_seen: list[str] = []
    misc_reason = ""

    sources = [(name, base) for name, base in _CHROMIUM.items()]
    for name, base in sources:
        result = _read_chromium(name, base)
        if result.cookie and (
            not expected_steam_id or result.steam_id == expected_steam_id
        ):
            return result
        if result.app_bound:
            app_bound_seen.append(name)
        elif result.reason not in ("not installed", ""):
            misc_reason = result.reason

    firefox = _read_firefox()
    if firefox.cookie and (
        not expected_steam_id or firefox.steam_id == expected_steam_id
    ):
        return firefox

    if app_bound_seen:
        return CookieResult(
            app_bound=True,
            reason="app-bound",
            browser=", ".join(app_bound_seen),
        )
    return CookieResult(reason=misc_reason or "no Steam cookie found")
