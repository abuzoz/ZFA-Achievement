"""Reads one game's achievement totals and prints them as JSON.

Run as a child process by scanwin.py -- Steamworks binds one AppID per
process, so a library-wide scan spawns one of these per game.
"""

from __future__ import annotations

import json
import sys
import time

from steamapi import SteamClient, SteamError


def main() -> int:
    if len(sys.argv) < 3:
        print(json.dumps({"error": "usage"}), flush=True)
        return 2

    app_id = int(sys.argv[1])
    dll_path = sys.argv[2]

    try:
        client = SteamClient(dll_path, app_id)
    except SteamError as exc:
        print(json.dumps({"app_id": app_id, "error": " ".join(str(exc).split())}))
        return 1

    client.request_stats()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        client.run_callbacks()
        if client.achievement_count():
            break
        time.sleep(0.15)

    achievements = client.achievements()
    total = len(achievements)
    unlocked = sum(1 for a in achievements if a.unlocked)
    client.close()

    print(
        json.dumps(
            {"app_id": app_id, "total": total, "unlocked": unlocked},
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
