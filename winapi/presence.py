"""Whether someone is at the machine: time since their last keyboard or mouse input, and whether a program needs the display.

Both are read-only observations. Workspace never changes the lock, screen-saver or
power settings, and never simulates input to hold them off.
"""

import ctypes
from typing import Final

lazy from win32more.Windows.Win32.System.Power import ES_DISPLAY_REQUIRED, CallNtPowerInformation, SystemExecutionState
lazy from win32more.Windows.Win32.System.SystemInformation import GetTickCount64
lazy from win32more.Windows.Win32.UI.Input.KeyboardAndMouse import LASTINPUTINFO, GetLastInputInfo

_TICKS: Final = 1 << 32


def elapsed(now: int, then: int) -> int:
    """Milliseconds from the 32-bit tick `then` to the 64-bit tick `now`, across the 49.7-day wrap of 32-bit ticks."""
    return (now - then) % _TICKS


def idle_ms() -> int:
    """Milliseconds since this session's last keyboard or mouse input; 0 when Windows doesn't say."""
    info = LASTINPUTINFO(cbSize=ctypes.sizeof(LASTINPUTINFO))
    if not GetLastInputInfo(info):
        return 0
    return elapsed(GetTickCount64(), info.dwTime)


def display_required() -> bool:
    """Whether any process asks Windows to keep the display on; True when Windows doesn't say.

    Measured on this machine on 2026-11-04: the system execution state reads
    ES_DISPLAY_REQUIRED while another process holds SetThreadExecutionState's
    display flag or a PowerSetRequest display request, and clears when it exits.
    A system-only request leaves the display flag clear."""
    state = ctypes.c_ulong()
    if CallNtPowerInformation(SystemExecutionState, None, 0, ctypes.byref(state), ctypes.sizeof(state)) != 0:
        return True
    return bool(state.value & ES_DISPLAY_REQUIRED)
