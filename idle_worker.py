"""Idles a single game: tells Steam the app is running so card drops accrue.

One process per AppID -- Steamworks binds one app per process. Started and
stopped by idlerwin.py; prints heartbeats so the parent can show status.
"""

from __future__ import annotations

import sys
import time

from steamapi import SteamClient, SteamError


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: idle_worker.py <app_id> <dll_path> [minutes]", flush=True)
        return 2

    app_id = int(sys.argv[1])
    dll_path = sys.argv[2]
    limit_minutes = float(sys.argv[3]) if len(sys.argv) > 3 else 0.0

    try:
        client = SteamClient(dll_path, app_id)
    except SteamError as exc:
        # One line: the parent tracks status by the last line it read.
        print("ERROR " + " ".join(str(exc).split()), flush=True)
        return 1

    print(f"IDLING {app_id}", flush=True)
    started = time.monotonic()
    try:
        while True:
            client.run_callbacks()
            time.sleep(1.0)
            elapsed = time.monotonic() - started
            if limit_minutes and elapsed >= limit_minutes * 60:
                print("DONE time limit reached", flush=True)
                break
            if int(elapsed) % 30 == 0:
                print(f"ALIVE {int(elapsed)}", flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
