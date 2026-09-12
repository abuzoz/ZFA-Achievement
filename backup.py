"""Snapshots of achievement state, written before any change is committed.

Modifying achievements is not reversible through Steam's UI, so we keep a
per-game record of what was locked/unlocked before we touched it. That makes
"undo" possible and gives the user a safety net for the one risky operation
in the app.
"""

from __future__ import annotations

import json
import os
from datetime import datetime

import steamlib

BACKUP_DIR = os.path.join(steamlib.CONFIG_DIR, "backups")


def _path(app_id: int) -> str:
    return os.path.join(BACKUP_DIR, f"{app_id}.json")


def save_snapshot(app_id: int, game_name: str, achievements) -> None:
    """Record current unlock state. Keeps the last few snapshots per game."""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    history = _load(app_id)
    history.setdefault("game", game_name)
    history.setdefault("snapshots", [])
    history["snapshots"].append(
        {
            "when": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "state": {a.api_name: bool(a.unlocked) for a in achievements},
        }
    )
    history["snapshots"] = history["snapshots"][-10:]  # keep the last 10
    with open(_path(app_id), "w", encoding="utf-8") as handle:
        json.dump(history, handle, ensure_ascii=False, indent=2)


def _load(app_id: int) -> dict:
    try:
        with open(_path(app_id), "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


def latest_snapshot(app_id: int) -> dict | None:
    """The most recent saved {api_name: unlocked} map, or None."""
    history = _load(app_id)
    snapshots = history.get("snapshots") or []
    return snapshots[-1] if snapshots else None
