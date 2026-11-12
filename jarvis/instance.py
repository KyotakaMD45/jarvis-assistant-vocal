"""Single instance + control channel.

Only one Jarvis may use the microphone. A second launch (double-click on start.bat) asks the
running one to show its window and exits. `start.bat --quit` stops the running instance.
The running instance listens on 127.0.0.1 with a random token stored in .jarvis.instance.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import json
import os
import secrets
import socket
import threading
import time
from collections.abc import Callable

from jarvis.logger import get_logger
from jarvis.paths import ROOT

log = get_logger(__name__)

INFO_PATH = ROOT / ".jarvis.instance"
_MUTEX_NAME = "Local\\JarvisVoiceAssistant_C_JARVIS"
_ERROR_ALREADY_EXISTS = 183
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.CreateMutexW.restype = wt.HANDLE
_kernel32.OpenProcess.restype = wt.HANDLE


def wait_for_process_exit(pid: int, timeout: float = 20.0) -> None:
    handle = _kernel32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
    if handle:
        _kernel32.WaitForSingleObject(handle, int(timeout * 1000))
        _kernel32.CloseHandle(handle)


class InstanceLock:
    def __init__(self):
        self._mutex = None
        self._server: socket.socket | None = None
        self.token = secrets.token_hex(16)

    def acquire(self) -> bool:
        """True if this process is now the only Jarvis."""
        self._mutex = _kernel32.CreateMutexW(None, False, _MUTEX_NAME)
        if ctypes.get_last_error() == _ERROR_ALREADY_EXISTS:
            _kernel32.CloseHandle(self._mutex)
            self._mutex = None
            return False
        return True

    def acquire_waiting(self, timeout: float = 20.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.acquire():
                return True
            time.sleep(0.3)
        return False

    def serve(self, handlers: dict[str, Callable[[], None]]) -> None:
        """Accept commands ("show", "quit", "restart") from other launches."""
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.bind(("127.0.0.1", 0))
        self._server.listen(4)
        port = self._server.getsockname()[1]
        INFO_PATH.write_text(json.dumps({"pid": os.getpid(), "port": port, "token": self.token}), encoding="utf-8")

        def loop() -> None:
            while True:
                try:
                    conn, _ = self._server.accept()
                except OSError:
                    return
                with conn:
                    try:
                        conn.settimeout(3)
                        message = json.loads(conn.recv(1024).decode("utf-8"))
                        if not secrets.compare_digest(str(message.get("token", "")), self.token):
                            conn.sendall(b"denied")
                            continue
                        handler = handlers.get(message.get("cmd"))
                        conn.sendall(b"ok" if handler else b"unknown")
                    except (OSError, ValueError):
                        continue
                if handler:
                    threading.Thread(target=handler, daemon=True).start()

        threading.Thread(target=loop, name="instance-server", daemon=True).start()

    def release(self) -> None:
        if self._server is not None:
            try:
                self._server.close()
            except OSError:
                pass
        try:
            info = json.loads(INFO_PATH.read_text(encoding="utf-8"))
            if info.get("pid") == os.getpid():
                INFO_PATH.unlink()
        except (OSError, ValueError):
            pass
        if self._mutex:
            _kernel32.CloseHandle(self._mutex)
            self._mutex = None


def send_command(cmd: str, timeout: float = 3.0) -> bool:
    """Ask the running Jarvis to do something. False if none is running/answering."""
    try:
        info = json.loads(INFO_PATH.read_text(encoding="utf-8"))
        with socket.create_connection(("127.0.0.1", int(info["port"])), timeout=timeout) as conn:
            conn.sendall(json.dumps({"token": info["token"], "cmd": cmd}).encode("utf-8"))
            return conn.recv(16) == b"ok"
    except (OSError, ValueError, KeyError):
        return False
