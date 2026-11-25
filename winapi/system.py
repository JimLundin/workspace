import ctypes
from collections.abc import Iterator, Sequence
from ctypes import wintypes
from dataclasses import dataclass
from enum import IntEnum
from typing import Final, NewType

from winapi._core import (
    ULONG_PTR,
    CloseHandle,
    CreateEventW,
    PostMessageW,
    fn,
    kernel32,
    last_error,
    user32,
)


class WindowMessage(IntEnum):
    CLOSE = 0x0010
    INPUT = 0x00FF
    """Raw input arrived (see `keyboard_devices.watch_input`)."""
    KEYDOWN = 0x0100
    KEYUP = 0x0101
    SYSKEYDOWN = 0x0104
    SYSKEYUP = 0x0105
    TIMER = 0x0113
    LBUTTONUP = 0x0202
    RBUTTONUP = 0x0205
    APP = 0x8000
    """The first message number an application may define for itself."""


_MB_ICONHAND: Final = 0x10

_ERROR_ALREADY_EXISTS: Final = 183
_INFINITE: Final = 0xFFFF_FFFF

_GetMessageW = fn(
    user32,
    "GetMessageW",
    wintypes.BOOL,
    ctypes.POINTER(wintypes.MSG),
    wintypes.HWND,
    wintypes.UINT,
    wintypes.UINT,
)
_PostQuitMessage = fn(user32, "PostQuitMessage", None, ctypes.c_int)
_SetTimer = fn(
    user32,
    "SetTimer",
    ULONG_PTR,
    wintypes.HWND,
    ULONG_PTR,
    wintypes.UINT,
    ctypes.c_void_p,
)
_KillTimer = fn(user32, "KillTimer", wintypes.BOOL, wintypes.HWND, ULONG_PTR)
_MessageBoxW = fn(
    user32,
    "MessageBoxW",
    ctypes.c_int,
    wintypes.HWND,
    wintypes.LPCWSTR,
    wintypes.LPCWSTR,
    wintypes.UINT,
)
_GetTickCount = fn(kernel32, "GetTickCount", wintypes.DWORD)
_GetCurrentProcess = fn(kernel32, "GetCurrentProcess", wintypes.HANDLE)
_SetPriorityClass = fn(
    kernel32, "SetPriorityClass", wintypes.BOOL, wintypes.HANDLE, wintypes.DWORD
)
_SetProcessInformation = fn(
    kernel32,
    "SetProcessInformation",
    wintypes.BOOL,
    wintypes.HANDLE,
    ctypes.c_int,
    ctypes.c_void_p,
    wintypes.DWORD,
)
_CreateMutexW = fn(
    kernel32,
    "CreateMutexW",
    wintypes.HANDLE,
    ctypes.c_void_p,
    wintypes.BOOL,
    wintypes.LPCWSTR,
)
_WaitForMultipleObjects = fn(
    kernel32,
    "WaitForMultipleObjects",
    wintypes.DWORD,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.HANDLE),
    wintypes.BOOL,
    wintypes.DWORD,
)

_HIGH_PRIORITY_CLASS: Final = 0x0080
_PROCESS_POWER_THROTTLING: Final = 4
_THROTTLE_EXECUTION_SPEED: Final = 0x1


class _PowerThrottling(ctypes.Structure):
    _fields_ = (
        ("Version", wintypes.ULONG),
        ("ControlMask", wintypes.ULONG),
        ("StateMask", wintypes.ULONG),
    )


Lock = NewType("Lock", int)
EventHandle = NewType("EventHandle", int)


@dataclass(frozen=True, slots=True)
class Message:
    hwnd: int
    message: int
    wparam: int
    lparam: int
    time: int
    """When Windows posted it, in `tick_count` milliseconds."""


def messages() -> Iterator[Message]:
    msg = wintypes.MSG()
    while _GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        yield Message(
            int(msg.hWnd or 0),
            int(msg.message),
            int(msg.wParam),
            int(msg.lParam),
            int(msg.time),
        )


def post_quit() -> None:
    _PostQuitMessage(0)


def post_message(hwnd: int, message: int, wparam: int, lparam: int) -> bool:
    return bool(PostMessageW(hwnd, message, wparam, lparam))


def tick_count() -> int:
    return int(_GetTickCount())


def set_timer(ms: int) -> int:
    return int(_SetTimer(None, 0, ms, None))


def kill_timer(timer: int) -> None:
    _KillTimer(None, timer)


def set_window_timer(hwnd: int, ms: int) -> int:
    timer = int(_SetTimer(hwnd, 1, ms, None))
    if not timer:
        raise OSError("Windows refused the capture watchdog timer.")
    return timer


def error_box(text: str, title: str) -> None:
    _MessageBoxW(None, text, title, _MB_ICONHAND)


def create_lock(name: str) -> Lock | None:
    handle: int | None = _CreateMutexW(None, False, name)
    if handle and ctypes.get_last_error() == _ERROR_ALREADY_EXISTS:
        CloseHandle(handle)
        return None
    return Lock(handle) if handle else None


def release_lock(lock: Lock) -> None:
    CloseHandle(lock)


def create_event() -> EventHandle:
    handle: int | None = CreateEventW(None, False, False, None)
    if not handle:
        raise last_error()
    return EventHandle(handle)


def close_event(event: EventHandle) -> None:
    CloseHandle(event)


def wait_any(
    events: Sequence[EventHandle], timeout_ms: int | None = None
) -> int | None:
    handles = (wintypes.HANDLE * len(events))(*events)
    index = int(
        _WaitForMultipleObjects(
            len(events),
            handles,
            False,
            _INFINITE if timeout_ms is None else timeout_ms,
        )
    )
    if index < len(events):
        return index
    if index == 0x102:
        return None
    raise last_error()


def keep_responsive() -> None:
    process = _GetCurrentProcess()
    if not _SetPriorityClass(process, _HIGH_PRIORITY_CLASS):
        raise last_error()
    state = _PowerThrottling(1, _THROTTLE_EXECUTION_SPEED, 0)
    if not _SetProcessInformation(
        process,
        _PROCESS_POWER_THROTTLING,
        ctypes.byref(state),
        ctypes.sizeof(state),
    ):
        raise last_error()
