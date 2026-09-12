"""Builds the command line for a child process, whether we run as loose .py
files or as a single frozen PyInstaller .exe.

The app needs one process per Steam AppID, so it re-launches itself in "worker"
modes. As scripts that means `python <script>.py …`; frozen it means
`app.exe --worker <mode> …`, dispatched by dispatch() at startup.
"""

from __future__ import annotations

import os
import sys

FROZEN = getattr(sys, "frozen", False)
HERE = os.path.dirname(os.path.abspath(__file__))

# mode -> script filename for the non-frozen case
_SCRIPTS = {
    "manager": "manager.py",
    "idle": "idle_worker.py",
    "scan": "scan_worker.py",
}


def child_command(mode: str, *args) -> list[str]:
    str_args = [str(a) for a in args]
    if FROZEN:
        return [sys.executable, "--worker", mode, *str_args]
    return [sys.executable, os.path.join(HERE, _SCRIPTS[mode]), *str_args]


def dispatch() -> bool:
    """If launched as a worker, run that worker and return True. Otherwise
    return False so the caller starts the normal GUI.

    Only meaningful when frozen; as scripts each worker has its own entry
    point, but handling it here too keeps one code path.
    """
    if len(sys.argv) >= 2 and sys.argv[1] == "--worker":
        mode = sys.argv[2] if len(sys.argv) > 2 else ""
        worker_args = sys.argv[3:]
        sys.argv = [sys.argv[0], *worker_args]
        if mode == "manager":
            import manager

            raise SystemExit(manager.main())
        if mode == "idle":
            import idle_worker

            raise SystemExit(idle_worker.main())
        if mode == "scan":
            import scan_worker

            raise SystemExit(scan_worker.main())
        print(f"unknown worker mode: {mode}")
        raise SystemExit(2)
    return False
