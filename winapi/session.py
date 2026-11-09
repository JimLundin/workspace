"""The interactive session's lock state, and its lock and unlock notifications."""

import ctypes
from ctypes import wintypes
from enum import Enum, auto
from typing import Final

lazy from win32more.Windows.Win32.System.RemoteDesktop import (
    NOTIFY_FOR_THIS_SESSION,
    WTS_CURRENT_SESSION,
    WTSINFOEXW,
    WTSFreeMemory,
    WTSQuerySessionInformationW,
    WTSSessionInfoEx,
)

from winapi._core import fn, last_error, wtsapi32

WM_WTSSESSION_CHANGE: Final = 0x02B1
WM_DISPLAYCHANGE: Final = 0x007E


_WTSRegisterSessionNotification = fn(wtsapi32, "WTSRegisterSessionNotification", wintypes.BOOL, wintypes.HWND, wintypes.DWORD)
_WTSUnRegisterSessionNotification = fn(wtsapi32, "WTSUnRegisterSessionNotification", wintypes.BOOL, wintypes.HWND)


class Change(Enum):
    LOCKED = auto()
    UNLOCKED = auto()


_CHANGES: Final = frozendict({7: Change.LOCKED, 8: Change.UNLOCKED})
"""WTS_SESSION_LOCK and WTS_SESSION_UNLOCK."""


def change(message: int, wparam: int) -> Change | None:
    """A window message as a lock change; every other session event is None."""
    return _CHANGES.get(wparam) if message == WM_WTSSESSION_CHANGE else None


def subscribe(hwnd: int) -> None:
    """`hwnd` receives WM_WTSSESSION_CHANGE for this session until `unsubscribe`."""
    if not _WTSRegisterSessionNotification(hwnd, NOTIFY_FOR_THIS_SESSION):
        raise last_error()


def unsubscribe(hwnd: int) -> None:
    _WTSUnRegisterSessionNotification(hwnd)


_LOCKED: Final = frozendict({0: True, 1: False})
"""WTS_SESSIONSTATE_LOCK and WTS_SESSIONSTATE_UNLOCK; Windows may report neither."""


def locked() -> bool | None:
    """Whether this session is locked now; None when Windows doesn't say."""
    buffer = ctypes.c_wchar_p()
    size = ctypes.c_ulong()
    if not WTSQuerySessionInformationW(None, WTS_CURRENT_SESSION, WTSSessionInfoEx, ctypes.byref(buffer), ctypes.byref(size)):
        return None
    try:
        if size.value < ctypes.sizeof(WTSINFOEXW):
            return None
        info = ctypes.cast(buffer, ctypes.POINTER(WTSINFOEXW)).contents
        return _LOCKED.get(info.Data.WTSInfoExLevel1.SessionFlags) if info.Level == 1 else None
    finally:
        WTSFreeMemory(buffer)
