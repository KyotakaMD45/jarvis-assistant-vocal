"""CPU, RAM and battery readings through the Windows API (ctypes, no extra dependency)."""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt

from jarvis.logger import get_logger

log = get_logger(__name__)


class _FileTime(ctypes.Structure):
    _fields_ = [("low", wt.DWORD), ("high", wt.DWORD)]

    def value(self) -> int:
        return (self.high << 32) | self.low


class _MemoryStatus(ctypes.Structure):
    _fields_ = [
        ("dwLength", wt.DWORD), ("dwMemoryLoad", wt.DWORD),
        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


class _PowerStatus(ctypes.Structure):
    _fields_ = [
        ("ACLineStatus", ctypes.c_ubyte), ("BatteryFlag", ctypes.c_ubyte),
        ("BatteryLifePercent", ctypes.c_ubyte), ("SystemStatusFlag", ctypes.c_ubyte),
        ("BatteryLifeTime", wt.DWORD), ("BatteryFullLifeTime", wt.DWORD),
    ]


class SystemStats:
    """Call `read()` every second or two; CPU usage is computed between two calls."""

    def __init__(self):
        self._kernel32 = ctypes.WinDLL("kernel32")
        self._prev: tuple[int, int, int] | None = None

    def _cpu_percent(self) -> float | None:
        idle, kernel, user = _FileTime(), _FileTime(), _FileTime()
        if not self._kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
            return None
        now = (idle.value(), kernel.value(), user.value())
        prev, self._prev = self._prev, now
        if prev is None:
            return None
        d_idle = now[0] - prev[0]
        d_total = (now[1] - prev[1]) + (now[2] - prev[2])  # kernel time includes idle time
        if d_total <= 0:
            return None
        return max(0.0, min(100.0, 100.0 * (d_total - d_idle) / d_total))

    def read(self) -> dict:
        stats: dict = {"cpu": None, "ram": None, "ram_used_gb": None, "ram_total_gb": None,
                       "battery": None, "charging": None}
        try:
            stats["cpu"] = self._cpu_percent()
            mem = _MemoryStatus()
            mem.dwLength = ctypes.sizeof(mem)
            if self._kernel32.GlobalMemoryStatusEx(ctypes.byref(mem)):
                stats["ram"] = float(mem.dwMemoryLoad)
                stats["ram_total_gb"] = round(mem.ullTotalPhys / 2**30, 1)
                stats["ram_used_gb"] = round((mem.ullTotalPhys - mem.ullAvailPhys) / 2**30, 1)
            power = _PowerStatus()
            if self._kernel32.GetSystemPowerStatus(ctypes.byref(power)):
                if power.BatteryLifePercent != 255 and not power.BatteryFlag & 128:  # 128 = no battery
                    stats["battery"] = int(power.BatteryLifePercent)
                stats["charging"] = power.ACLineStatus == 1
        except Exception as exc:  # noqa: BLE001 - stats are decorative, never fail
            log.debug("System stats failed: %r", exc)
        return stats
