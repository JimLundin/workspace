"""The low-level keyboard hook, keyboard input sent as if typed, and the cursor position."""

import ctypes
from collections.abc import Callable, Sequence
from ctypes import wintypes
from dataclasses import dataclass
from typing import Final

from winapi._core import LRESULT, ULONG_PTR, fn, kernel32, user32
from winapi.shapes import require_input_count, utf16_units


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
_GetModuleHandleW = fn(kernel32, "GetModuleHandleW", wintypes.HMODULE, wintypes.LPCWSTR)
_SendInput = fn(user32, "SendInput", wintypes.UINT, wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
_MapVirtualKeyW = fn(user32, "MapVirtualKeyW", wintypes.UINT, wintypes.UINT, wintypes.UINT)
_GetCursorPos = fn(user32, "GetCursorPos", wintypes.BOOL, ctypes.POINTER(wintypes.POINT))

LLKHF_EXTENDED, LLKHF_INJECTED = 0x01, 0x10
KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP, KEYEVENTF_UNICODE, KEYEVENTF_SCANCODE = 0x0001, 0x0002, 0x0004, 0x0008
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
    handle: int | None = _SetWindowsHookExW(_WH_KEYBOARD_LL, callback, _GetModuleHandleW(None), 0)
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


def send_key(vk: int, scancode: int, flags: int, extra: int) -> None:
    _send([_key(vk, scancode, flags, extra)])


def send_scancodes(strokes: Sequence[tuple[int, bool]], extra: int) -> None:
    """Physical keys by scancode, as a keyboard would send them (used by tests)."""
    _send([_key(0, code, KEYEVENTF_SCANCODE | (0 if down else KEYEVENTF_KEYUP), extra) for code, down in strokes])


def type_text(text: str, extra: int) -> None:
    """Types text as characters, whatever the keyboard layout. A newline presses Enter."""
    enter = scancode_for(_VK_RETURN)
    events: list[INPUT] = []
    for i, line in enumerate(text.split("\n")):
        if i:
            events += [_key(_VK_RETURN, enter, 0, extra), _key(_VK_RETURN, enter, KEYEVENTF_KEYUP, extra)]
        events += [_key(0, unit, KEYEVENTF_UNICODE | up, extra) for unit in utf16_units(line) for up in (0, KEYEVENTF_KEYUP)]
    if events:
        _send(events)


def cursor_position() -> tuple[int, int]:
    point = wintypes.POINT()
    _GetCursorPos(ctypes.byref(point))
    return int(point.x), int(point.y)
