"""Minimal ctypes wrapper around the Steamworks flat API (steam_api64.dll).

Only the ISteamUserStats / ISteamUtils surface needed for reading and writing
achievements is bound. The DLL is shipped with almost every Steam game, so the
user points us at a copy instead of us redistributing it.
"""

from __future__ import annotations

import ctypes
import os
from ctypes import (
    POINTER,
    byref,
    c_bool,
    c_char_p,
    c_int,
    c_uint8,
    c_uint32,
    c_void_p,
)
from dataclasses import dataclass

from i18n import n


class SteamError(Exception):
    pass


# Accessor names change with each SDK bump; probe newest first.
_USER_STATS_ACCESSORS = [f"SteamAPI_SteamUserStats_v{v:03d}" for v in range(20, 8, -1)]
_UTILS_ACCESSORS = [f"SteamAPI_SteamUtils_v{v:03d}" for v in range(20, 8, -1)]
_USER_STATS_IFACES = [f"STEAMUSERSTATS_INTERFACE_VERSION{v:03d}" for v in range(20, 8, -1)]
_UTILS_IFACES = [f"SteamUtils{v:03d}" for v in range(20, 8, -1)]


@dataclass
class Achievement:
    api_name: str
    display_name: str
    description: str
    hidden: bool
    unlocked: bool
    unlock_time: int  # unix seconds, 0 when locked
    icon_handle: int


class SteamClient:
    """Owns one Steamworks session. One AppID per process -- that is a hard
    Steamworks limit, so the picker spawns a child process per game."""

    def __init__(self, dll_path: str, app_id: int):
        self.app_id = int(app_id)
        self.dll_path = dll_path
        self._initialized = False

        # Steamworks reads the AppID from the environment at init time.
        os.environ["SteamAppId"] = str(self.app_id)
        os.environ["SteamGameId"] = str(self.app_id)

        directory = os.path.dirname(os.path.abspath(dll_path))
        if hasattr(os, "add_dll_directory") and os.path.isdir(directory):
            self._dll_dir = os.add_dll_directory(directory)
        else:
            self._dll_dir = None

        try:
            self._lib = ctypes.CDLL(dll_path)
        except OSError as exc:
            raise SteamError(n("steam.dll_load_failed", path=dll_path, error=exc)) from exc

        self._bind_core()
        self._init_api()
        self._user_stats = self._get_interface(_USER_STATS_ACCESSORS, _USER_STATS_IFACES)
        self._utils = self._get_interface(_UTILS_ACCESSORS, _UTILS_IFACES)
        self._bind_stats()

    # ------------------------------------------------------------------ setup

    def _bind_core(self) -> None:
        lib = self._lib
        self._run_callbacks = getattr(lib, "SteamAPI_RunCallbacks", None)
        if self._run_callbacks is not None:
            self._run_callbacks.restype = None
            self._run_callbacks.argtypes = []

        self._shutdown = getattr(lib, "SteamAPI_Shutdown", None)
        if self._shutdown is not None:
            self._shutdown.restype = None
            self._shutdown.argtypes = []

    def _init_api(self) -> None:
        lib = self._lib

        # SDK 1.59+ exposes SteamAPI_InitFlat, which reports why init failed.
        init_flat = getattr(lib, "SteamAPI_InitFlat", None)
        if init_flat is not None:
            init_flat.restype = c_int
            init_flat.argtypes = [c_char_p]
            buffer = ctypes.create_string_buffer(1024)
            result = init_flat(buffer)
            if result != 0:
                raise SteamError(
                    n(
                        "steam.init_failed_detail",
                        detail=buffer.value.decode("utf-8", "replace"),
                    )
                )
            self._initialized = True
            return

        init = getattr(lib, "SteamAPI_Init", None)
        if init is None:
            raise SteamError(n("steam.not_a_dll"))
        init.restype = c_bool
        init.argtypes = []
        if not init():
            raise SteamError(n("steam.init_failed"))
        self._initialized = True

    def _get_interface(self, accessors: list[str], iface_versions: list[str]) -> c_void_p:
        for name in accessors:
            fn = getattr(self._lib, name, None)
            if fn is None:
                continue
            fn.restype = c_void_p
            fn.argtypes = []
            ptr = fn()
            if ptr:
                return c_void_p(ptr)

        # Fallback for older DLLs without the versioned flat accessors.
        create = getattr(self._lib, "SteamInternal_CreateInterface", None)
        if create is not None:
            create.restype = c_void_p
            create.argtypes = [c_char_p]
            for version in iface_versions:
                ptr = create(version.encode())
                if ptr:
                    return c_void_p(ptr)

        raise SteamError(n("steam.no_interface", name=accessors[0]))

    def _bind_stats(self) -> None:
        lib = self._lib

        def bind(name, restype, argtypes):
            fn = getattr(lib, name, None)
            if fn is None:
                raise SteamError(n("steam.missing_export", name=name))
            fn.restype = restype
            fn.argtypes = argtypes
            return fn

        self._request_stats = bind(
            "SteamAPI_ISteamUserStats_RequestCurrentStats", c_bool, [c_void_p]
        )
        self._num_achievements = bind(
            "SteamAPI_ISteamUserStats_GetNumAchievements", c_uint32, [c_void_p]
        )
        self._achievement_name = bind(
            "SteamAPI_ISteamUserStats_GetAchievementName", c_char_p, [c_void_p, c_uint32]
        )
        self._get_achievement_and_time = bind(
            "SteamAPI_ISteamUserStats_GetAchievementAndUnlockTime",
            c_bool,
            [c_void_p, c_char_p, POINTER(c_bool), POINTER(c_uint32)],
        )
        self._display_attribute = bind(
            "SteamAPI_ISteamUserStats_GetAchievementDisplayAttribute",
            c_char_p,
            [c_void_p, c_char_p, c_char_p],
        )
        self._set_achievement = bind(
            "SteamAPI_ISteamUserStats_SetAchievement", c_bool, [c_void_p, c_char_p]
        )
        self._clear_achievement = bind(
            "SteamAPI_ISteamUserStats_ClearAchievement", c_bool, [c_void_p, c_char_p]
        )
        self._store_stats = bind(
            "SteamAPI_ISteamUserStats_StoreStats", c_bool, [c_void_p]
        )
        self._achievement_icon = bind(
            "SteamAPI_ISteamUserStats_GetAchievementIcon", c_int, [c_void_p, c_char_p]
        )

        self._image_size = bind(
            "SteamAPI_ISteamUtils_GetImageSize",
            c_bool,
            [c_void_p, c_int, POINTER(c_uint32), POINTER(c_uint32)],
        )
        self._image_rgba = bind(
            "SteamAPI_ISteamUtils_GetImageRGBA",
            c_bool,
            [c_void_p, c_int, POINTER(c_uint8), c_int],
        )

    # ------------------------------------------------------------------- api

    def run_callbacks(self) -> None:
        if self._run_callbacks is not None:
            self._run_callbacks()

    def request_stats(self) -> bool:
        return bool(self._request_stats(self._user_stats))

    def achievement_count(self) -> int:
        return int(self._num_achievements(self._user_stats))

    def _attribute(self, api_name: bytes, key: str) -> str:
        raw = self._display_attribute(self._user_stats, api_name, key.encode())
        return raw.decode("utf-8", "replace") if raw else ""

    def achievements(self) -> list[Achievement]:
        out: list[Achievement] = []
        for index in range(self.achievement_count()):
            raw_name = self._achievement_name(self._user_stats, index)
            if not raw_name:
                continue
            achieved = c_bool(False)
            unlock_time = c_uint32(0)
            self._get_achievement_and_time(
                self._user_stats, raw_name, byref(achieved), byref(unlock_time)
            )
            out.append(
                Achievement(
                    api_name=raw_name.decode("utf-8", "replace"),
                    display_name=self._attribute(raw_name, "name") or raw_name.decode(),
                    description=self._attribute(raw_name, "desc"),
                    hidden=self._attribute(raw_name, "hidden") == "1",
                    unlocked=bool(achieved.value),
                    unlock_time=int(unlock_time.value),
                    icon_handle=int(self._achievement_icon(self._user_stats, raw_name)),
                )
            )
        return out

    def set_achievement(self, api_name: str, unlocked: bool) -> bool:
        encoded = api_name.encode()
        if unlocked:
            return bool(self._set_achievement(self._user_stats, encoded))
        return bool(self._clear_achievement(self._user_stats, encoded))

    def store(self) -> bool:
        ok = bool(self._store_stats(self._user_stats))
        self.run_callbacks()
        return ok

    def icon_rgba(self, api_name: str) -> tuple[int, int, bytes] | None:
        """Returns (width, height, rgba bytes) once Steam has cached the icon."""
        handle = int(self._achievement_icon(self._user_stats, api_name.encode()))
        if handle <= 0:
            return None
        width = c_uint32(0)
        height = c_uint32(0)
        if not self._image_size(self._utils, handle, byref(width), byref(height)):
            return None
        size = width.value * height.value * 4
        if size <= 0:
            return None
        buffer = (c_uint8 * size)()
        if not self._image_rgba(self._utils, handle, buffer, size):
            return None
        return width.value, height.value, bytes(buffer)

    def close(self) -> None:
        if self._initialized and self._shutdown is not None:
            self._shutdown()
            self._initialized = False
        if self._dll_dir is not None:
            self._dll_dir.close()
            self._dll_dir = None
