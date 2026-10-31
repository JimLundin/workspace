"""Windows power observations."""

import ctypes
from ctypes import wintypes

from winapi._core import fn, kernel32
from winapi.machine_status import Battery, Power, PowerUnavailable


class PowerStatus(ctypes.Structure):
    ac: int
    flags: int
    percent: int
    saver: int
    seconds: int
    full_seconds: int
    _fields_ = (
        ("ac", ctypes.c_ubyte),
        ("flags", ctypes.c_ubyte),
        ("percent", ctypes.c_ubyte),
        ("saver", ctypes.c_ubyte),
        ("seconds", wintypes.DWORD),
        ("full_seconds", wintypes.DWORD),
    )


_GetSystemPowerStatus = fn(kernel32, "GetSystemPowerStatus", wintypes.BOOL, ctypes.POINTER(PowerStatus))


def power() -> Power:
    status = PowerStatus()
    return power_from_status(status if _GetSystemPowerStatus(ctypes.byref(status)) else None)


def power_from_status(status: PowerStatus | None) -> Power:
    """Validate one native observation before publishing the toolbar's power state."""
    if status is None or status.flags == 255:
        return PowerUnavailable.UNKNOWN
    if status.flags & 128:
        return PowerUnavailable.NO_BATTERY
    if not 0 <= status.percent <= 100:
        return PowerUnavailable.UNKNOWN
    return Battery(int(status.percent), powered=status.ac == 1, charging=bool(status.flags & 8))
