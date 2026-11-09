"""The low-level keyboard hook, keyboard input sent as if typed, and the cursor position."""

import ctypes
from collections.abc import Callable, Sequence
from ctypes import wintypes
from dataclasses import dataclass
from itertools import chain
from typing import Final

from winapi._core import LRESULT, ULONG_PTR, GetCursorPos, GetModuleHandleW, fn, user32
from winapi.shapes import Point, require_input_count, utf16_units


class KBDLLHOOKSTRUCT(ctypes.Structure):
    vkCode: int
    scanCode: int
    flags: int
    time: int
    dwExtraInfo: int
    _fields_ = (
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    )


class KEYBDINPUT(ctypes.Structure):
    wVk: int
    wScan: int
    dwFlags: int
    time: int
    dwExtraInfo: int
    _fields_ = (
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    )


class MOUSEINPUT(ctypes.Structure):
    dx: int
    dy: int
    mouseData: int
    dwFlags: int
    time: int
    dwExtraInfo: int
    _fields_ = (
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    )


class InputUnion(ctypes.Union):
    ki: KEYBDINPUT
    mi: MOUSEINPUT
    _fields_ = (("ki", KEYBDINPUT), ("mi", MOUSEINPUT))


class INPUT(ctypes.Structure):
    type: int
    u: InputUnion
    _fields_ = (("type", wintypes.DWORD), ("u", InputUnion))


# Struct sizes must match Windows exactly, or SendInput silently does nothing.
if ctypes.sizeof(INPUT) != (40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28):
    raise ImportError(f"INPUT is {ctypes.sizeof(INPUT)} bytes; Windows expects a different size")

HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
_SetWindowsHookExW = fn(user32, "SetWindowsHookExW", wintypes.HHOOK, ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD)
_CallNextHookEx = fn(user32, "CallNextHookEx", LRESULT, wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
_UnhookWindowsHookEx = fn(user32, "UnhookWindowsHookEx", wintypes.BOOL, wintypes.HHOOK)
_SendInput = fn(user32, "SendInput", wintypes.UINT, wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
_MapVirtualKeyW = fn(user32, "MapVirtualKeyW", wintypes.UINT, wintypes.UINT, wintypes.UINT)

LLKHF_EXTENDED, LLKHF_INJECTED = 0x01, 0x10
_KEYEVENTF_EXTENDEDKEY, _KEYEVENTF_KEYUP, _KEYEVENTF_UNICODE, _KEYEVENTF_SCANCODE = 0x0001, 0x0002, 0x0004, 0x0008
_KEY_DOWNS: Final = frozenset({0x0100, 0x0104})
"""WM_KEYDOWN and WM_SYSKEYDOWN."""
_KEY_UPS: Final = frozenset({0x0101, 0x0105})
"""WM_KEYUP and WM_SYSKEYUP."""
_WH_KEYBOARD_LL: Final = 13
_INPUT_KEYBOARD: Final = 1
_MAPVK_VK_TO_VSC: Final = 0
_VK_RETURN: Final = 0x0D

HookProc = Callable[[int, int, int], int]
"""(code, wparam, lparam) -> result, as Windows calls a low-level hook."""


@dataclass(frozen=True, slots=True)
class KeyEvent:
    """What a low-level keyboard hook receives for one key."""

    vk: int
    scancode: int
    flags: int
    time: int
    extra: int

    @property
    def extended(self) -> bool:
        """An extended key (arrows, the right-hand modifiers, numpad Enter...), which shares a scancode with a plain one."""
        return bool(self.flags & LLKHF_EXTENDED)

    @property
    def injected(self) -> bool:
        """Sent by a program, not typed on a keyboard."""
        return bool(self.flags & LLKHF_INJECTED)


def transition(wparam: int) -> bool | None:
    """What a low-level keyboard hook message is: True for a key going down, False for up, None for neither."""
    return True if wparam in _KEY_DOWNS else False if wparam in _KEY_UPS else None


@dataclass(frozen=True, slots=True)
class Hook:
    """An installed hook. Holds the callback so it stays alive while installed."""

    handle: int
    callback: object


def read_key_event(lparam: int) -> KeyEvent:
    kb = ctypes.cast(lparam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
    return KeyEvent(int(kb.vkCode), int(kb.scanCode), int(kb.flags), int(kb.time), int(kb.dwExtraInfo))


def set_keyboard_hook(proc: HookProc) -> Hook | None:
    callback = HOOKPROC(proc)
    handle: int | None = _SetWindowsHookExW(_WH_KEYBOARD_LL, callback, GetModuleHandleW(None), 0)
    return Hook(handle, callback) if handle else None


def remove_hook(hook: Hook) -> None:
    _UnhookWindowsHookEx(hook.handle)


def call_next_hook(code: int, wparam: int, lparam: int) -> int:
    return int(_CallNextHookEx(None, code, wparam, lparam))


def scancode_for(vk: int) -> int:
    """The key's scancode, from Windows' own layout table."""
    return int(_MapVirtualKeyW(vk, _MAPVK_VK_TO_VSC))


def _key(vk: int, scancode: int, flags: int, extra: int) -> INPUT:
    return INPUT(_INPUT_KEYBOARD, InputUnion(ki=KEYBDINPUT(vk, scancode, flags, 0, extra)))


def _submit(events: Sequence[INPUT]) -> int:
    """All in one call, so the user's own input can't land in the middle."""
    array = (INPUT * len(events))(*events)
    return int(_SendInput(len(events), array, ctypes.sizeof(INPUT)))


def _send(events: Sequence[INPUT]) -> int:
    sent = _submit(events)
    require_input_count(sent, len(events))
    return sent


def send_key(vk: int, *, down: bool, extended: bool, extra: int) -> None:
    """One key, with the scancode some programs read, from Windows' own layout table."""
    flags = (0 if down else _KEYEVENTF_KEYUP) | (_KEYEVENTF_EXTENDEDKEY if extended else 0)
    _send([_key(vk, scancode_for(vk), flags, extra)])


def send_scancodes(strokes: Sequence[tuple[int, bool]], extra: int) -> None:
    """Physical keys by scancode, as a keyboard would send them (used by tests)."""
    _send([_key(0, code, _KEYEVENTF_SCANCODE | (0 if down else _KEYEVENTF_KEYUP), extra) for code, down in strokes])


def type_text(text: str, extra: int) -> None:
    """Types text as characters, whatever the keyboard layout. A newline presses Enter."""
    enter = scancode_for(_VK_RETURN)
    events = tuple(
        event
        for i, line in enumerate(text.split("\n"))
        for event in chain(
            (_key(_VK_RETURN, enter, flags, extra) for flags in ((0, _KEYEVENTF_KEYUP) if i else ())),
            (_key(0, unit, _KEYEVENTF_UNICODE | up, extra) for unit in utf16_units(line) for up in (0, _KEYEVENTF_KEYUP)),
        )
    )
    if events:
        _send(events)


def cursor_position() -> Point:
    point = wintypes.POINT()
    GetCursorPos(ctypes.byref(point))
    return Point(int(point.x), int(point.y))
