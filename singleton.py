"""Single-instance guard for the GUI.

A loopback socket doubles as the lock *and* a tiny IPC channel: the first
instance binds a fixed 127.0.0.1 port and listens; a second launch fails to
bind, connects to the primary to ask it to surface its window, then exits with
a message. A socket lock (unlike a lock file) is released automatically by the
OS the moment the owning process dies, so a crash never leaves a stale lock
that blocks the next launch.

Only the GUI process reaches this code — worker subprocesses (manager / scan /
idle) are dispatched earlier in launcher.dispatch() and never call main().
"""

from __future__ import annotations

import socket
import threading

HOST = "127.0.0.1"      # loopback only: no external exposure, no firewall prompt
PORT = 52017            # fixed high port unique to this app
_PING = b"ZFA-PING\n"
_PONG = b"ZFA-PONG\n"


def acquire() -> socket.socket | None:
    """Try to become the primary instance.

    Returns a listening socket to keep for the process lifetime, or None if the
    port is already taken (another instance, or — rarely — an unrelated app).
    """
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        # Deliberately no SO_REUSEADDR: we WANT bind to fail if it is held.
        srv.bind((HOST, PORT))
        srv.listen(5)
    except OSError:
        srv.close()
        return None
    return srv


def serve(srv: socket.socket, on_show) -> None:
    """Answer pings from later launches. For each valid ping, reply and invoke
    `on_show` (which must marshal itself onto the GUI thread)."""

    def loop():
        while True:
            try:
                conn, _ = srv.accept()
            except OSError:
                return  # socket closed during shutdown
            try:
                data = conn.recv(64)
                if data.strip() == _PING.strip():
                    conn.sendall(_PONG)
            except OSError:
                data = b""
            finally:
                conn.close()
            if data.strip() == _PING.strip():
                try:
                    on_show()
                except Exception:
                    pass

    threading.Thread(target=loop, daemon=True).start()


def signal_existing() -> bool:
    """Ask an already-running instance to surface its window.

    Returns True only if our own primary answered the handshake — so a port
    held by some unrelated program does NOT read as "already running" (the
    caller then falls back to starting normally)."""
    try:
        with socket.create_connection((HOST, PORT), timeout=2) as sock:
            sock.sendall(_PING)
            reply = sock.recv(64)
        return reply.strip() == _PONG.strip()
    except OSError:
        return False
