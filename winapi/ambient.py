"""Windows power and optional, bounded geolocation observations."""

import ctypes
import math
import threading
import time
from ctypes import wintypes

lazy from win32more import FAILED
lazy from win32more.Windows.Devices.Geolocation import BasicGeoposition, Geolocator, Geoposition, PositionStatus
lazy from win32more.Windows.Foundation import IAsyncInfo, IAsyncOperation, TimeSpan
lazy from win32more.Windows.Win32.System.WinRT import RO_INIT_MULTITHREADED, RoInitialize, RoUninitialize

from assistant.ambient import Battery, Power, PowerUnavailable
from winapi._core import fn, kernel32


class PowerStatus(ctypes.Structure):
    ac: int
    flags: int
    percent: int
    saver: int
    seconds: int
    full_seconds: int
    _fields_ = (("ac", ctypes.c_ubyte), ("flags", ctypes.c_ubyte), ("percent", ctypes.c_ubyte),
               ("saver", ctypes.c_ubyte), ("seconds", wintypes.DWORD), ("full_seconds", wintypes.DWORD))


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
    return Battery(int(status.percent), status.ac == 1, bool(status.flags & 8))


def location(cancelled: threading.Event) -> tuple[float, float] | None:
    """Use an already available Windows location; never request consent or infer IP location."""
    if FAILED(RoInitialize(RO_INIT_MULTITHREADED)):
        return None
    operation: IAsyncOperation[Geoposition] | None = None
    info: IAsyncInfo | None = None
    locator: Geolocator | None = None
    position: BasicGeoposition | None = None
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
