"""Watchdog: restart Apex if it stops without being asked to.

Started by the running assistant (`python -m jarvis.watchdog <pid>`), it waits for that process to
end. A normal quit or restart writes the marker file CLEAN_EXIT first; if it is missing, the
process died (crash, killed...) and Apex is started again. More than 3 crashes in 10 minutes:
stop trying (logged), so a broken install cannot restart forever.
"""
from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import time

from jarvis.paths import ROOT

CLEAN_EXIT = ROOT / ".clean_exit"
CRASHES = ROOT / ".crash_times"
SYNCHRONIZE, INFINITE = 0x00100000, 0xFFFFFFFF


def _log(text: str) -> None:
    try:
        with open(ROOT / "jarvis.log", "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S,000") + f" WARNING jarvis.watchdog: {text}\n")
    except OSError:
        pass


def _wait(pid: int) -> None:
    kernel32 = ctypes.WinDLL("kernel32")
    handle = kernel32.OpenProcess(SYNCHRONIZE, False, pid)
    if not handle:
        return  # already gone
    try:
        kernel32.WaitForSingleObject(handle, INFINITE)
    finally:
        kernel32.CloseHandle(handle)


def main(pid: int) -> int:
    _wait(pid)
    time.sleep(1.0)
    if CLEAN_EXIT.exists():
        return 0
    now = time.time()
    try:
        recent = [t for t in json.loads(CRASHES.read_text()) if now - t < 600]
    except (OSError, ValueError):
        recent = []
    recent.append(now)
    try:
        CRASHES.write_text(json.dumps(recent))
    except OSError:
        pass
    if len(recent) > 3:
        _log(f"Apex stopped unexpectedly {len(recent)} times in 10 minutes: not restarting it. See crash.log.")
        return 1
    _log("Apex stopped unexpectedly (no quit was asked): restarting it.")
    pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    exe = pythonw if os.path.exists(pythonw) else sys.executable
    flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    subprocess.Popen([exe, "-m", "jarvis"], cwd=str(ROOT), creationflags=flags, close_fds=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(int(sys.argv[1])))
