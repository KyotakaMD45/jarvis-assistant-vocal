"""Low-level Windows helpers (ctypes only): folders, windows, keys, power, volume, brightness."""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os
import subprocess
import uuid
from pathlib import Path

from jarvis.logger import get_logger

log = get_logger(__name__)

user32 = ctypes.WinDLL("user32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32")
ole32 = ctypes.WinDLL("ole32")
CREATE_NO_WINDOW = 0x08000000

# ---------------------------------------------------------------------------------------
# Known folders (handles OneDrive-redirected Documents/Pictures)
# ---------------------------------------------------------------------------------------
_FOLDER_IDS = {
    "desktop": "B4BFCC3A-DB2C-424C-B029-7FE99A87C641",
    "documents": "FDD39AD0-238F-46AF-ADB4-6C85480369C7",
    "downloads": "374DE290-123F-4565-9164-39C4925E467B",
    "music": "4BD8D571-6D19-48D3-BE97-422220080E43",
    "pictures": "33E28130-4E1E-4676-835A-98395C3BC3BB",
    "videos": "18989B1D-99B5-455B-841C-AB7C74E4DDFC",
}


class _GUID(ctypes.Structure):
    _fields_ = [("data", ctypes.c_byte * 16)]


def known_folder(name: str) -> Path:
    guid = _GUID()
    ctypes.memmove(ctypes.byref(guid), uuid.UUID(_FOLDER_IDS[name]).bytes_le, 16)
    path_ptr = ctypes.c_wchar_p()
    try:
        if shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(path_ptr)) == 0:
            return Path(path_ptr.value)
    finally:
        if path_ptr:
            ole32.CoTaskMemFree(path_ptr)
    return Path.home() / name.capitalize()


# ---------------------------------------------------------------------------------------
# Windows
# ---------------------------------------------------------------------------------------
_EnumProc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
user32.EnumWindows.argtypes = [_EnumProc, wt.LPARAM]
user32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
user32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
WM_CLOSE = 0x0010


def _process_name(pid: int) -> str:
    try:
        import psutil

        return psutil.Process(pid).name()
    except Exception:  # noqa: BLE001
        return ""


def list_windows() -> list[tuple[int, str, str]]:
    """Visible top-level windows with a title: (hwnd, title, process name)."""
    found: list[tuple[int, str, str]] = []

    def callback(hwnd, _lparam):
        if user32.IsWindowVisible(hwnd) and not user32.GetWindow(hwnd, 4):  # 4 = GW_OWNER
            length = user32.GetWindowTextLengthW(hwnd)
            if length:
                buffer = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buffer, length + 1)
                pid = wt.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                found.append((hwnd, buffer.value, _process_name(pid.value)))
        return True

    user32.EnumWindows(_EnumProc(callback), 0)
    return found


def close_window(hwnd: int) -> bool:
    """Polite close (like clicking X): the app can still ask to save."""
    return bool(user32.PostMessageW(hwnd, WM_CLOSE, 0, 0))


# ---------------------------------------------------------------------------------------
# Keys (media and volume keys work with every player)
# ---------------------------------------------------------------------------------------
VK = {"play_pause": 0xB3, "next": 0xB0, "previous": 0xB1, "stop": 0xB2,
      "volume_up": 0xAF, "volume_down": 0xAE, "volume_mute": 0xAD}


def press_key(name: str, times: int = 1) -> None:
    code = VK[name]
    for _ in range(times):
        user32.keybd_event(code, 0, 1, 0)       # KEYEVENTF_EXTENDEDKEY
        user32.keybd_event(code, 0, 1 | 2, 0)   # + KEYEVENTF_KEYUP


# ---------------------------------------------------------------------------------------
# Session / power
# ---------------------------------------------------------------------------------------
def lock_workstation() -> bool:
    return bool(user32.LockWorkStation())


def sleep_computer() -> None:
    ctypes.WinDLL("powrprof").SetSuspendState(0, 1, 0)


def shutdown(action: str, delay: int = 15) -> None:
    flag = {"shutdown": "/s", "restart": "/r"}[action]
    subprocess.run(["shutdown", flag, "/t", str(delay)], creationflags=CREATE_NO_WINDOW, check=False)


def cancel_shutdown() -> bool:
    result = subprocess.run(["shutdown", "/a"], creationflags=CREATE_NO_WINDOW, capture_output=True)
    return result.returncode == 0


# ---------------------------------------------------------------------------------------
# Master volume (Windows Core Audio through pycaw)
# ---------------------------------------------------------------------------------------
def _endpoint_volume():
    import comtypes

    try:
        comtypes.CoInitialize()
    except OSError:
        pass
    from pycaw.pycaw import AudioUtilities

    return AudioUtilities.GetSpeakers().EndpointVolume


def get_volume() -> tuple[int, bool]:
    ev = _endpoint_volume()
    return round(ev.GetMasterVolumeLevelScalar() * 100), bool(ev.GetMute())


def set_volume(percent: int) -> int:
    percent = max(0, min(100, int(percent)))
    ev = _endpoint_volume()
    ev.SetMasterVolumeLevelScalar(percent / 100, None)
    if percent > 0:
        ev.SetMute(0, None)
    return percent


def set_mute(muted: bool) -> None:
    _endpoint_volume().SetMute(1 if muted else 0, None)


# ---------------------------------------------------------------------------------------
# Laptop screen brightness (WMI; not available on most external monitors)
# ---------------------------------------------------------------------------------------
def _powershell(script: str, timeout: float = 10) -> str:
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True, timeout=timeout, creationflags=CREATE_NO_WINDOW,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip()[:300] or "PowerShell failed")
    return result.stdout.strip()


def get_brightness() -> int:
    out = _powershell("(Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightness -ErrorAction Stop).CurrentBrightness")
    return int(out.splitlines()[0])


def set_brightness(percent: int) -> int:
    percent = max(5, min(100, int(percent)))
    _powershell(
        "Invoke-CimMethod -InputObject (Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods "
        f"-ErrorAction Stop) -MethodName WmiSetBrightness -Arguments @{{Timeout=1; Brightness={percent}}} | Out-Null"
    )
    return percent


def open_target(target: str) -> None:
    """Open an exe, file, folder, URL or URI with its default handler."""
    os.startfile(target)  # noqa: S606 - targets come from Jarvis's own tables/index, not raw speech
