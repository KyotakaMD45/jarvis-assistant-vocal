"""Keyboard, mouse wheel, clipboard and window control through the Windows API (ctypes only).

Safety: Jarvis never types or presses Enter into a terminal or the Run box (that would be the
same as running shell commands), and keyboard shortcuts come from a fixed list.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os
import time

from jarvis.logger import get_logger

log = get_logger(__name__)

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

# ---------------------------------------------------------------------------------------
# SendInput
# ---------------------------------------------------------------------------------------
INPUT_MOUSE, INPUT_KEYBOARD = 0, 1
KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP = 0x1, 0x2
MOUSEEVENTF_WHEEL = 0x0800


class _KeybdInput(ctypes.Structure):
    _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD), ("time", wt.DWORD),
                ("dwExtraInfo", ctypes.c_size_t)]


class _MouseInput(ctypes.Structure):
    _fields_ = [("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD), ("dwFlags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _HardwareInput(ctypes.Structure):
    _fields_ = [("uMsg", wt.DWORD), ("wParamL", wt.WORD), ("wParamH", wt.WORD)]


class _InputUnion(ctypes.Union):
    _fields_ = [("ki", _KeybdInput), ("mi", _MouseInput), ("hi", _HardwareInput)]


class _Input(ctypes.Structure):
    _fields_ = [("type", wt.DWORD), ("u", _InputUnion)]


user32.SendInput.argtypes = [wt.UINT, ctypes.POINTER(_Input), ctypes.c_int]
user32.SendInput.restype = wt.UINT

KEYS = {
    "ctrl": 0x11, "shift": 0x10, "alt": 0x12, "win": 0x5B, "tab": 0x09, "enter": 0x0D, "esc": 0x1B,
    "backspace": 0x08, "delete": 0x2E, "space": 0x20, "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    "pageup": 0x21, "pagedown": 0x22, "end": 0x23, "home": 0x24, "plus": 0xBB, "minus": 0xBD,
    "f4": 0x73, "f5": 0x74, "f11": 0x7A,
}
_EXTENDED = {0x2E, 0x25, 0x26, 0x27, 0x28, 0x21, 0x22, 0x23, 0x24, 0x5B}


def _vk(name: str) -> int:
    if name in KEYS:
        return KEYS[name]
    if len(name) == 1 and name.isalnum():
        return ord(name.upper())
    raise ValueError(f"unknown key {name!r}")


def _key_input(vk: int, up: bool) -> _Input:
    flags = (KEYEVENTF_KEYUP if up else 0) | (KEYEVENTF_EXTENDEDKEY if vk in _EXTENDED else 0)
    return _Input(type=INPUT_KEYBOARD, u=_InputUnion(ki=_KeybdInput(wVk=vk, wScan=0, dwFlags=flags, time=0, dwExtraInfo=0)))


def send_combo(combo: str) -> None:
    """Press a shortcut like "ctrl+shift+t" (keys pressed in order, released in reverse)."""
    vks = [_vk(k.strip()) for k in combo.lower().split("+")]
    events = [_key_input(v, False) for v in vks] + [_key_input(v, True) for v in reversed(vks)]
    array = (_Input * len(events))(*events)
    if user32.SendInput(len(events), array, ctypes.sizeof(_Input)) != len(events):
        log.warning("SendInput %s failed (error %d)", combo, ctypes.get_last_error())


def scroll(notches: int) -> None:
    """Mouse wheel under the pointer: positive = up."""
    data = ctypes.c_uint32(int(notches) * 120).value
    event = _Input(type=INPUT_MOUSE, u=_InputUnion(mi=_MouseInput(dx=0, dy=0, mouseData=data, dwFlags=MOUSEEVENTF_WHEEL,
                                                                    time=0, dwExtraInfo=0)))
    user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(_Input))


MOUSE_BUTTONS = {"left": (0x0002, 0x0004), "right": (0x0008, 0x0010)}


def click(button: str = "left", double: bool = False) -> None:
    """Click where the mouse pointer is."""
    down, up = MOUSE_BUTTONS[button]
    events = []
    for _ in range(2 if double else 1):
        for flag in (down, up):
            events.append(_Input(type=INPUT_MOUSE, u=_InputUnion(mi=_MouseInput(dx=0, dy=0, mouseData=0, dwFlags=flag,
                                                                                  time=0, dwExtraInfo=0))))
    array = (_Input * len(events))(*events)
    user32.SendInput(len(events), array, ctypes.sizeof(_Input))


# ---------------------------------------------------------------------------------------
# Clipboard (Unicode text)
# ---------------------------------------------------------------------------------------
CF_UNICODETEXT, GMEM_MOVEABLE = 13, 0x2
kernel32.GlobalAlloc.argtypes = [wt.UINT, ctypes.c_size_t]
kernel32.GlobalAlloc.restype = wt.HGLOBAL
kernel32.GlobalLock.argtypes = [wt.HGLOBAL]
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalUnlock.argtypes = [wt.HGLOBAL]
user32.OpenClipboard.argtypes = [wt.HWND]
user32.SetClipboardData.argtypes = [wt.UINT, wt.HANDLE]
user32.SetClipboardData.restype = wt.HANDLE
user32.GetClipboardData.argtypes = [wt.UINT]
user32.GetClipboardData.restype = wt.HANDLE


def _open_clipboard() -> bool:
    for _ in range(20):
        if user32.OpenClipboard(None):
            return True
        time.sleep(0.03)
    return False


def get_clipboard() -> str | None:
    if not _open_clipboard():
        return None
    try:
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return None
        ptr = kernel32.GlobalLock(handle)
        try:
            return ctypes.wstring_at(ptr) if ptr else None
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


def paste_text(text: str) -> bool:
    """Type text in the focused field through the clipboard (exact, fast), then restore the clipboard."""
    previous = get_clipboard()
    if not set_clipboard(text):
        return False
    send_combo("ctrl+v")
    time.sleep(0.5)
    if previous is not None:
        set_clipboard(previous)
    return True


def set_clipboard(text: str) -> bool:
    data = ctypes.create_unicode_buffer(text)
    size = ctypes.sizeof(data)
    if not _open_clipboard():
        return False
    try:
        user32.EmptyClipboard()
        handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, size)
        ptr = kernel32.GlobalLock(handle)
        ctypes.memmove(ptr, data, size)
        kernel32.GlobalUnlock(handle)
        return bool(user32.SetClipboardData(CF_UNICODETEXT, handle))
    finally:
        user32.CloseClipboard()


# ---------------------------------------------------------------------------------------
# Windows
# ---------------------------------------------------------------------------------------
GW_HWNDNEXT, WM_CLOSE = 2, 0x0010
SW_MINIMIZE, SW_MAXIMIZE, SW_RESTORE = 6, 3, 9
user32.GetWindow.restype = wt.HWND
user32.GetWindow.argtypes = [wt.HWND, wt.UINT]
user32.GetForegroundWindow.restype = wt.HWND
user32.GetClassNameW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]

HUD_TITLES = ("K.N.U.L.L.", "Knull", "A.P.E.X.", "Apex", "J.A.R.V.I.S.", "Jarvis")
SHELL_CLASSES = {"ConsoleWindowClass", "CASCADIA_HOSTING_WINDOW_CLASS", "PseudoConsoleWindow", "mintty",
                 "VirtualConsoleClass", "PuTTY"}
RUN_TITLES = {"exécuter", "executer", "run"}


def window_info(hwnd) -> tuple[str, str, int]:
    cls = ctypes.create_unicode_buffer(256)
    title = ctypes.create_unicode_buffer(512)
    user32.GetClassNameW(hwnd, cls, 256)
    user32.GetWindowTextW(hwnd, title, 512)
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return cls.value, title.value, pid.value


def is_hud(hwnd) -> bool:
    if not hwnd:
        return False
    _cls, title, pid = window_info(hwnd)
    return pid == os.getpid() or title in HUD_TITLES


def is_shell(hwnd) -> bool:
    """Terminals and the Run box: Jarvis never types or presses Enter there."""
    if not hwnd:
        return False
    cls, title, _pid = window_info(hwnd)
    return cls in SHELL_CLASSES or (cls == "#32770" and title.strip().lower() in RUN_TITLES) \
        or "powershell" in title.lower() or title.lower().startswith(("invite de commandes", "command prompt"))


def foreground():
    return user32.GetForegroundWindow()


def target_window():
    """The window the user is working in: the foreground one, or the next real window below the HUD."""
    hwnd = foreground()
    if not is_hud(hwnd):
        return hwnd
    nxt = hwnd
    for _ in range(200):
        nxt = user32.GetWindow(nxt, GW_HWNDNEXT)
        if not nxt:
            return None
        if user32.IsWindowVisible(nxt) and not user32.IsIconic(nxt) and not is_hud(nxt):
            _cls, title, _pid = window_info(nxt)
            if title and title not in ("Program Manager",):
                return nxt
    return None


def focus(hwnd) -> bool:
    if not hwnd:
        return False
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    # Windows only lets a process take the focus right after input; a harmless Alt tap unlocks it.
    send_combo("alt")
    user32.SetForegroundWindow(hwnd)
    for _ in range(20):
        if foreground() == hwnd:
            return True
        time.sleep(0.03)
    return foreground() == hwnd


def show_window(hwnd, how: int) -> None:
    user32.ShowWindow(hwnd, how)


def close(hwnd) -> None:
    user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)


# An app opened in the same voice turn takes a moment to appear: typing must wait for it.
_opened = {"at": 0.0, "fg": None, "before": set()}
last_target_fresh = False  # the last wait_for_target() waited for an app opened just before


def mark_app_opened() -> None:
    """Call just BEFORE opening an app: remembers which windows already existed."""
    from jarvis.winctl import list_windows

    try:
        before = {int(w[0]) for w in list_windows()}
    except Exception:  # noqa: BLE001
        before = set()
    _opened.update(at=time.monotonic(), fg=foreground(), before=before)


def wait_for_target(max_wait: float = 6.0):
    """Return the window to type into (after a just-opened app has appeared), or None."""
    global last_target_fresh
    started = time.monotonic()
    last_target_fresh = started - _opened["at"] < 10.0
    if last_target_fresh:
        while time.monotonic() - started < max_wait:
            fg = foreground()
            if fg and not is_hud(fg):
                if int(fg) not in _opened["before"]:
                    break  # the new window is there
                if time.monotonic() - started > 3.5 and fg != _opened["fg"]:
                    break  # an already open window came to the front
            time.sleep(0.1)
        time.sleep(0.8)  # let it finish loading its editor
        _opened["at"] = 0.0
    hwnd = target_window()
    if hwnd and hwnd != foreground():
        focus(hwnd)
    return hwnd
