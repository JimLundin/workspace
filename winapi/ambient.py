"""Windows power and optional, bounded geolocation observations."""
# pyright: reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnknownVariableType=false, reportMissingTypeStubs=false

import ctypes
import math
import threading
import time
from ctypes import wintypes
from typing import Any

from assistant.ambient import Battery, Power, PowerUnavailable
from winapi._core import fn, kernel32


class SYSTEM_POWER_STATUS(ctypes.Structure):  # noqa: N801  # Windows structure name.
    _fields_ = (("ac", ctypes.c_ubyte), ("flags", ctypes.c_ubyte), ("percent", ctypes.c_ubyte),
               ("saver", ctypes.c_ubyte), ("seconds", wintypes.DWORD), ("full_seconds", wintypes.DWORD))


_GetSystemPowerStatus = fn(kernel32, "GetSystemPowerStatus", wintypes.BOOL, ctypes.POINTER(SYSTEM_POWER_STATUS))


def power() -> Power:
    status = SYSTEM_POWER_STATUS()
    return power_from_status(status if _GetSystemPowerStatus(ctypes.byref(status)) else None)


def power_from_status(status: SYSTEM_POWER_STATUS | None) -> Power:
    """Validate one native observation before publishing the toolbar's power state."""
    if status is None or status.flags == 255:
        return PowerUnavailable.UNKNOWN
    if status.flags & 128:
        return PowerUnavailable.NO_BATTERY
    if not 0 <= status.percent <= 100:
        return PowerUnavailable.UNKNOWN
    return Battery(int(status.percent), status.ac == 1, bool(status.flags & 8))


def location(cancelled: threading.Event) -> tuple[float, float] | None:
    """Use an already available Windows location; never request consent or infer IP location."""
    from win32more import FAILED  # noqa: PLC0415
    from win32more.Windows.Devices.Geolocation import Geolocator, PositionStatus  # noqa: PLC0415
    from win32more.Windows.Foundation import IAsyncInfo, TimeSpan  # noqa: PLC0415
    from win32more.Windows.Win32.System.WinRT import RO_INIT_MULTITHREADED, RoInitialize, RoUninitialize  # noqa: PLC0415

    if FAILED(RoInitialize(RO_INIT_MULTITHREADED)):
        return None
    operation: Any = None
    info: Any = None
    locator: Any = None
    position: Any = None
    try:
        locator = Geolocator()
        if locator.LocationStatus in (PositionStatus.Disabled, PositionStatus.NotAvailable):
            return None
        operation = locator.GetGeopositionAsyncWithAgeAndTimeout(TimeSpan(3_000_000_000), TimeSpan(80_000_000))
        info = operation.as_(IAsyncInfo)
        deadline = time.monotonic() + 9
        while info.Status == 0:
            if cancelled.wait(.05) or time.monotonic() >= deadline:
                info.Cancel()
                return None
        if info.Status != 1:
            return None
        position = operation.GetResults().Coordinate.Point.Position
        latitude, longitude = float(position.Latitude), float(position.Longitude)
        if math.isfinite(latitude) and math.isfinite(longitude) and -90 <= latitude <= 90 and -180 <= longitude <= 180:
            return latitude, longitude
        return None
    except (OSError, ValueError):
        return None
    finally:
        position = info = operation = locator = None
        RoUninitialize()
