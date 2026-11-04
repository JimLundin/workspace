"""The interactive session's lock state, and its lock and unlock notifications."""

import ctypes
from ctypes import wintypes
from enum import Enum, auto
from typing import Final

from winapi._core import fn, last_error, wtsapi32

WM_WTSSESSION_CHANGE: Final = 0x02B1
WM_DISPLAYCHANGE: Final = 0x007E
_NOTIFY_FOR_THIS_SESSION: Final = 0
_WTS_CURRENT_SESSION: Final = 0xFFFF_FFFF
_WTS_SESSION_INFO_EX: Final = 25


class SessionInfoLevel1(ctypes.Structure):
    """WTSINFOEX_LEVEL1_W."""

    SessionFlags: int
    _fields_ = (
        ("SessionId", wintypes.ULONG),
        ("SessionState", ctypes.c_int),
        ("SessionFlags", wintypes.LONG),
        ("WinStationName", wintypes.WCHAR * 33),
        ("UserName", wintypes.WCHAR * 21),
        ("DomainName", wintypes.WCHAR * 18),
        ("LogonTime", wintypes.LARGE_INTEGER),
        ("ConnectTime", wintypes.LARGE_INTEGER),
        ("DisconnectTime", wintypes.LARGE_INTEGER),
        ("LastInputTime", wintypes.LARGE_INTEGER),
        ("CurrentTime", wintypes.LARGE_INTEGER),
        ("IncomingBytes", wintypes.DWORD),
        ("OutgoingBytes", wintypes.DWORD),
        ("IncomingFrames", wintypes.DWORD),
        ("OutgoingFrames", wintypes.DWORD),
        ("IncomingCompressedBytes", wintypes.DWORD),
        ("OutgoingCompressedBytes", wintypes.DWORD),
    )


class SessionInfo(ctypes.Structure):
    """WTSINFOEXW."""

    Level: int
    Data: SessionInfoLevel1
    _fields_ = (("Level", wintypes.DWORD), ("Data", SessionInfoLevel1))


_WTSRegisterSessionNotification = fn(wtsapi32, "WTSRegisterSessionNotification", wintypes.BOOL, wintypes.HWND, wintypes.DWORD)
_WTSUnRegisterSessionNotification = fn(wtsapi32, "WTSUnRegisterSessionNotification", wintypes.BOOL, wintypes.HWND)
_WTSQuerySessionInformationW = fn(
    wtsapi32,
    "WTSQuerySessionInformationW",
    wintypes.BOOL,
    wintypes.HANDLE,
    wintypes.DWORD,
    ctypes.c_int,
    ctypes.POINTER(ctypes.POINTER(SessionInfo)),
    ctypes.POINTER(wintypes.DWORD),
)
_WTSFreeMemory = fn(wtsapi32, "WTSFreeMemory", None, ctypes.c_void_p)


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
    if not _WTSRegisterSessionNotification(hwnd, _NOTIFY_FOR_THIS_SESSION):
        raise last_error()


def unsubscribe(hwnd: int) -> None:
    _WTSUnRegisterSessionNotification(hwnd)


def locked() -> bool | None:
    """Whether this session is locked now; None when Windows doesn't say."""
    info = ctypes.POINTER(SessionInfo)()
    size = wintypes.DWORD()
    if not _WTSQuerySessionInformationW(None, _WTS_CURRENT_SESSION, _WTS_SESSION_INFO_EX, ctypes.byref(info), ctypes.byref(size)):
        return None
    try:
        if size.value < ctypes.sizeof(SessionInfo) or info.contents.Level != 1:
            return None
        match info.contents.Data.SessionFlags:  # WTS_SESSIONSTATE_LOCK, then WTS_SESSIONSTATE_UNLOCK.
            case 0:
                return True
            case 1:
                return False
            case _:
                return None
    finally:
        _WTSFreeMemory(info)
