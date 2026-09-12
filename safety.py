"""Keeps unexpected failures from turning into crashes or scary popups.

Every unhandled Tk callback exception lands in a log file instead of a
traceback dialog, so a broken corner of one window never takes the app down.
"""

from __future__ import annotations

import os
import traceback
from datetime import datetime

import steamlib

LOG_PATH = os.path.join(steamlib.CONFIG_DIR, "errors.log")


def log_error(context: str, exc: BaseException | None = None) -> None:
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    detail = "".join(traceback.format_exception(exc)) if exc else ""
    entry = f"[{stamp}] {context}\n{detail}\n"
    try:
        os.makedirs(steamlib.CONFIG_DIR, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as handle:
            handle.write(entry)
    except OSError:
        pass  # logging must never be the thing that breaks


def install(root) -> None:
    """Route Tk callback exceptions to the log instead of a crash dialog."""

    def handler(exc_type, exc_value, exc_traceback):
        log_error(f"unhandled in {type(root).__name__}", exc_value)

    root.report_callback_exception = handler

