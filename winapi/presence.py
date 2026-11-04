"""Whether someone is at the machine: time since their last keyboard or mouse input, and whether a program needs the display.

Both are read-only observations. Workspace never changes the lock, screen-saver or
power settings, and never simulates input to hold them off.
"""

import ctypes
from ctypes import wintypes
from typing import Final

from winapi._core import fn, kernel32, powrprof, user32


class LastInputInfo(ctypes.Structure):
    """LASTINPUTINFO."""

    time: int
    _fields_ = (("cbSize", wintypes.UINT), ("time", wintypes.DWORD))


_GetLastInputInfo = fn(user32, "GetLastInputInfo", wintypes.BOOL, ctypes.POINTER(LastInputInfo))
_GetTickCount64 = fn(kernel32, "GetTickCount64", ctypes.c_ulonglong)
_CallNtPowerInformation = fn(
    powrprof, "CallNtPowerInformation", wintypes.LONG, ctypes.c_int, ctypes.c_void_p, wintypes.ULONG, ctypes.c_void_p, wintypes.ULONG
)

_SYSTEM_EXECUTION_STATE: Final = 16
_ES_DISPLAY_REQUIRED: Final = 0x2
_TICKS: Final = 1 << 32


def elapsed(now: int, then: int) -> int:
    """Milliseconds from the 32-bit tick `then` to the 64-bit tick `now`, across the 49.7-day wrap of 32-bit ticks."""
    return (now - then) % _TICKS


def idle_ms() -> int:
    """Milliseconds since this session's last keyboard or mouse input; 0 when Windows doesn't say."""
    info = LastInputInfo(ctypes.sizeof(LastInputInfo), 0)
    if not _GetLastInputInfo(ctypes.byref(info)):
        return 0
    return elapsed(_GetTickCount64(), info.time)


def display_required() -> bool:
    """Whether any process asks Windows to keep the display on; True when Windows doesn't say.

    Measured on this machine on 2026-11-04: the system execution state reads
    ES_DISPLAY_REQUIRED while another process holds SetThreadExecutionState's
    display flag or a PowerSetRequest display request, and clears when it exits.
    A system-only request leaves the display flag clear."""
    state = wintypes.ULONG()
    if _CallNtPowerInformation(_SYSTEM_EXECUTION_STATE, None, 0, ctypes.byref(state), ctypes.sizeof(state)) != 0:
        return True
    return bool(state.value & _ES_DISPLAY_REQUIRED)
