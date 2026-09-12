"""Discovery of the local Steam install: library folders, installed games,
and a usable copy of steam_api64.dll."""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

CONFIG_DIR = os.path.join(
    os.environ.get("APPDATA", os.path.expanduser("~")), "SteamAchievementManager"
)
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
APP_NAMES_PATH = os.path.join(CONFIG_DIR, "appnames.json")

_KV = re.compile(r'"([^"]+)"\s+"([^"]*)"')

# Tools, runtimes and soundtracks that can never award achievements or cards.
IGNORED_APPS = {228980, 1070560, 1391110, 1493710, 250820, 250760, 365670, 223850}


@dataclass
class Game:
    app_id: int
    name: str
    install_dir: str = ""
    installed: bool = True
    playtime_minutes: int = 0


def load_config() -> dict:
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


def save_config(config: dict) -> None:
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as handle:
        json.dump(config, handle, indent=2)


def steam_path() -> str | None:
    """Steam install root, from the registry with fixed-path fallbacks."""
    try:
        import winreg

        for hive, key in (
            (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam"),
        ):
            try:
                with winreg.OpenKey(hive, key) as handle:
                    for value in ("SteamPath", "InstallPath"):
                        try:
                            path = winreg.QueryValueEx(handle, value)[0]
                        except OSError:
                            continue
                        path = os.path.normpath(path)
                        if os.path.isdir(path):
                            return path
            except OSError:
                continue
    except ImportError:
        pass

    for candidate in (
        r"C:\Program Files (x86)\Steam",
        r"C:\Program Files\Steam",
        os.path.expanduser(r"~\scoop\apps\steam\current"),
    ):
        if os.path.isdir(candidate):
            return candidate
    return None


def library_folders() -> list[str]:
    """Every steamapps directory Steam knows about, main library first."""
    root = steam_path()
    if not root:
        return []

    folders = [os.path.join(root, "steamapps")]
    seen = {folders[0].lower()}
    manifest = os.path.join(root, "steamapps", "libraryfolders.vdf")
    try:
        with open(manifest, "r", encoding="utf-8", errors="replace") as handle:
            text = handle.read()
    except OSError:
        text = ""

    for key, value in _KV.findall(text):
        # Old format keys the path by index ("1" "D:\\Games"), new one uses "path".
        if key.lower() != "path" and not key.isdigit():
            continue
        if not value or ":" not in value:
            continue
        steamapps = os.path.join(os.path.normpath(value.replace("\\\\", "\\")), "steamapps")
        # Windows paths differ only in case between the registry and the VDF.
        if os.path.isdir(steamapps) and steamapps.lower() not in seen:
            seen.add(steamapps.lower())
            folders.append(steamapps)

    return [folder for folder in folders if os.path.isdir(folder)]


def installed_games() -> list[Game]:
    """Parse appmanifest_*.acf across all libraries. No API key, works offline."""
    games: dict[int, Game] = {}
    for steamapps in library_folders():
        try:
            entries = os.listdir(steamapps)
        except OSError:
            continue
        for entry in entries:
            if not (entry.startswith("appmanifest_") and entry.endswith(".acf")):
                continue
            try:
                with open(
                    os.path.join(steamapps, entry), "r", encoding="utf-8", errors="replace"
                ) as handle:
                    fields = dict(_KV.findall(handle.read()))
            except OSError:
                continue

            try:
                app_id = int(fields.get("appid", ""))
            except ValueError:
                continue
            if app_id in IGNORED_APPS:
                continue

            install_dir = os.path.join(steamapps, "common", fields.get("installdir", ""))
            games[app_id] = Game(
                app_id=app_id,
                name=fields.get("name") or f"AppID {app_id}",
                install_dir=install_dir,
                installed=True,
            )

    return sorted(games.values(), key=lambda game: game.name.lower())


# --------------------------------------------------------------- whole library


def _apps_block(text: str) -> str:
    """Slice out the body of the `"apps" { ... }` section of a VDF file."""
    match = re.search(r'"apps"\s*\{', text)
    if not match:
        return ""
    start = match.end()
    depth = 1
    for index in range(start, len(text)):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start:index]
    return text[start:]


def local_library_apps() -> dict[int, int]:
    """Every AppID Steam has a local record for, mapped to playtime minutes.

    Read from userdata/<id>/config/localconfig.vdf -- covers the whole library,
    not just what is installed, and needs no login.
    """
    root = steam_path()
    if not root:
        return {}
    userdata = os.path.join(root, "userdata")
    if not os.path.isdir(userdata):
        return {}

    apps: dict[int, int] = {}
    for user_id in os.listdir(userdata):
        path = os.path.join(userdata, user_id, "config", "localconfig.vdf")
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                body = _apps_block(handle.read())
        except OSError:
            continue

        # Walk top-level "<appid>" { ... } entries, skipping nested sub-blocks.
        index, length = 0, len(body)
        while index < length:
            match = re.compile(r'"(\d+)"\s*\{').search(body, index)
            if not match:
                break
            app_id, depth, cursor = int(match.group(1)), 1, match.end()
            while cursor < length and depth:
                if body[cursor] == "{":
                    depth += 1
                elif body[cursor] == "}":
                    depth -= 1
                cursor += 1
            entry = body[match.end() : cursor - 1]
            playtime = re.search(r'"Playtime"\s+"(\d+)"', entry)
            if app_id not in IGNORED_APPS:
                apps[app_id] = max(
                    apps.get(app_id, 0), int(playtime.group(1)) if playtime else 0
                )
            index = cursor
    return apps


@dataclass
class Account:
    steam_id: str
    persona: str
    account_name: str

    @property
    def profile_url(self) -> str:
        return f"https://steamcommunity.com/profiles/{self.steam_id}"


def detect_account() -> Account | None:
    """Read the signed-in Steam account from config/loginusers.vdf.

    Saves the user from typing their profile URL: the numeric /profiles/<id>
    form works exactly like a vanity URL.
    """
    root = steam_path()
    if not root:
        return None
    path = os.path.join(root, "config", "loginusers.vdf")
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            text = handle.read()
    except OSError:
        return None

    best: tuple[int, Account] | None = None
    for match in re.finditer(r'"(7656\d{13})"\s*\{', text):
        steam_id = match.group(1)
        depth, cursor = 1, match.end()
        while cursor < len(text) and depth:
            if text[cursor] == "{":
                depth += 1
            elif text[cursor] == "}":
                depth -= 1
            cursor += 1
        fields = dict(_KV.findall(text[match.end() : cursor - 1]))

        account = Account(
            steam_id=steam_id,
            persona=fields.get("PersonaName", ""),
            account_name=fields.get("AccountName", ""),
        )
        # Prefer the most recent / auto-login account when several are stored.
        rank = int(fields.get("Timestamp", "0") or 0)
        if fields.get("MostRecent") == "1" or fields.get("AutoLogin") == "1":
            rank += 10**12
        if best is None or rank > best[0]:
            best = (rank, account)

    return best[1] if best else None


def autoconfigure(progress=None) -> dict:
    """Fill in anything the user would otherwise have to set by hand.

    Runs on every start; only writes keys that are missing or stale, so manual
    choices are never overwritten.
    """
    config = load_config()
    changed = False

    if not config.get("profile_url"):
        account = detect_account()
        if account:
            config["profile_url"] = account.profile_url
            config["persona"] = account.persona
            changed = True

    dll = config.get("dll_path", "")
    if not dll or not os.path.isfile(dll):
        found = find_steam_api_dll(progress=progress)
        if found:
            config["dll_path"] = found
            changed = True
        elif "dll_path" in config:
            config.pop("dll_path")
            changed = True

    if changed:
        save_config(config)
    return config


def load_app_names() -> dict[str, str]:
    try:
        with open(APP_NAMES_PATH, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


def save_app_names(names: dict[str, str]) -> None:
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(APP_NAMES_PATH, "w", encoding="utf-8") as handle:
        json.dump(names, handle, ensure_ascii=False)


def resolve_app_names(app_ids, progress=None, throttle: float = 0.4) -> dict[str, str]:
    """Look up missing game names on the store API and cache them on disk.

    The store rejects batched requests, so this is one call per unknown AppID --
    but the cache makes it a one-time cost per game.
    """
    names = load_app_names()
    unknown = [str(app_id) for app_id in app_ids if str(app_id) not in names]
    if not unknown:
        return names

    for index, app_id in enumerate(unknown, 1):
        if progress:
            progress(index, len(unknown))
        url = f"https://store.steampowered.com/api/appdetails?appids={app_id}&filters=basic"
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(request, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8", "replace"))
            entry = payload.get(app_id) or {}
            data = entry.get("data") or {}
            names[app_id] = data.get("name") or f"AppID {app_id}"
        except (urllib.error.URLError, ValueError, TimeoutError):
            names[app_id] = f"AppID {app_id}"
        time.sleep(throttle)

    save_app_names(names)
    return names


def all_owned_games(progress=None) -> list[Game]:
    """Installed games plus everything else in the local Steam library."""
    installed = {game.app_id: game for game in installed_games()}
    playtimes = local_library_apps()

    missing = [app_id for app_id in playtimes if app_id not in installed]
    names = resolve_app_names(missing, progress=progress) if missing else load_app_names()

    games = dict(installed)
    for app_id, minutes in playtimes.items():
        if app_id in games:
            games[app_id].playtime_minutes = minutes
            continue
        games[app_id] = Game(
            app_id=app_id,
            name=names.get(str(app_id), f"AppID {app_id}"),
            installed=False,
            playtime_minutes=minutes,
        )

    return sorted(games.values(), key=lambda game: game.name.lower())


def find_steam_api_dll(progress=None) -> str | None:
    """Locate a steam_api64.dll: next to this script, in the Steam client
    itself, then inside installed games (shallow walk, they ship it)."""
    here = os.path.dirname(os.path.abspath(__file__))
    local = os.path.join(here, "steam_api64.dll")
    if os.path.isfile(local):
        return local

    root = steam_path()
    if root:
        for candidate in (
            os.path.join(root, "steam_api64.dll"),
            os.path.join(root, "bin", "steam_api64.dll"),
        ):
            if os.path.isfile(candidate):
                return candidate

    for steamapps in library_folders():
        common = os.path.join(steamapps, "common")
        if not os.path.isdir(common):
            continue
        try:
            game_dirs = os.listdir(common)
        except OSError:
            continue
        for game_dir in game_dirs:
            base = os.path.join(common, game_dir)
            if progress:
                progress(game_dir)
            for current, subdirs, files in os.walk(base):
                if "steam_api64.dll" in files:
                    return os.path.join(current, "steam_api64.dll")
                # Depth limit: the DLL sits at the root or one or two levels in.
                if current[len(base) :].count(os.sep) >= 2:
                    subdirs.clear()
    return None
