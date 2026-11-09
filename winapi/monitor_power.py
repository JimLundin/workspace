"""Monitor power over DDC/CI: reading and setting VCP feature D6 (power mode).

Windows still drives a monitor that DDC/CI turns off, so the display
configuration, the monitor count and the work areas don't change: only the
panel goes dark. Monitors that don't answer DDC/CI, like most laptop panels,
report `Unanswered`.
"""

import ctypes
from collections.abc import Iterator
from ctypes import wintypes
from dataclasses import dataclass
from enum import Enum
from typing import Final

lazy from win32more.Windows.Win32.Devices.Display import (
    PHYSICAL_MONITOR,
    DestroyPhysicalMonitors,
    GetNumberOfPhysicalMonitorsFromHMONITOR,
    GetPhysicalMonitorsFromHMONITOR,
)

from cell import Cell
from winapi._core import dxva2, fn
from winapi.screen import Monitor, attached

# Windows reports a refused DDC/CI request through the thread's last error, which win32more's bindings don't keep.
_GetVCPFeatureAndVCPFeatureReply = fn(
    dxva2,
    "GetVCPFeatureAndVCPFeatureReply",
    wintypes.BOOL,
    wintypes.HANDLE,
    wintypes.BYTE,
    ctypes.c_void_p,
    ctypes.POINTER(wintypes.DWORD),
    ctypes.POINTER(wintypes.DWORD),
)
_SetVCPFeature = fn(dxva2, "SetVCPFeature", wintypes.BOOL, wintypes.HANDLE, wintypes.BYTE, wintypes.DWORD)

_POWER_MODE: Final = 0xD6


class Power(Enum):
    """MCCS power modes, by their D6 value."""

    ON = 1
    STANDBY = 2
    SUSPEND = 3
    OFF = 4
    """Display power management off: the panel is dark while the signal stays connected."""
    OFF_BY_BUTTON = 5


@dataclass(frozen=True, slots=True)
class Unanswered:
    """The monitor refused or didn't answer a DDC/CI request; `error` is Windows' code."""

    error: int


@dataclass(frozen=True, slots=True)
class Unrecognized:
    """The monitor answered with a power mode outside MCCS's table."""

    value: int


@dataclass(frozen=True, slots=True)
class Detached:
    """No open physical monitor for this monitor: it isn't attached, or Windows gave none."""


type Reading = Power | Unanswered | Unrecognized | Detached
type Applied = Power | Unanswered | Detached


@dataclass(frozen=True, slots=True)
class _Opened:
    """The open physical monitors behind one attached monitor, in the array Windows filled."""

    monitor: Monitor
    array: ctypes.Array[PHYSICAL_MONITOR]


def _opened() -> Iterator[_Opened]:
    """Open the physical monitors of each attached monitor that has any; the caller owns the arrays."""
    for hmonitor, monitor in attached():
        count = ctypes.c_uint32()
        if not GetNumberOfPhysicalMonitorsFromHMONITOR(hmonitor, ctypes.byref(count)) or count.value == 0:
            continue
        array = (PHYSICAL_MONITOR * count.value)()
        if GetPhysicalMonitorsFromHMONITOR(hmonitor, count.value, array):
            yield _Opened(monitor, array)


@dataclass(frozen=True, slots=True)
class _Handles:
    arrays: tuple[ctypes.Array[PHYSICAL_MONITOR], ...]
    handles: frozendict[Monitor, tuple[int, ...]]


@dataclass(frozen=True, slots=True)
class PhysicalMonitors:
    """Physical-monitor handles for every attached monitor, opened together and destroyed by `close`.

    Native ownership: the handle arrays stay allocated, and open, until `close`."""

    _opened: Cell[_Handles]

    @classmethod
    def open(cls) -> PhysicalMonitors:
        opened = tuple(_opened())
        arrays = tuple(physical.array for physical in opened)
        handles = frozendict((physical.monitor, tuple(int(entry.hPhysicalMonitor or 0) for entry in physical.array)) for physical in opened)
        return cls(Cell(_Handles(arrays, handles)))

    @property
    def _handles(self) -> frozendict[Monitor, tuple[int, ...]]:
        return self._opened.get().handles

    @property
    def monitors(self) -> frozenset[Monitor]:
        return frozenset(self._handles)

    def power(self, monitor: Monitor) -> Reading:
        """The first physical monitor's power mode."""
        handles = self._handles.get(monitor, ())
        if not handles:
            return Detached()
        current, maximum = wintypes.DWORD(), wintypes.DWORD()
        if not _GetVCPFeatureAndVCPFeatureReply(handles[0], _POWER_MODE, None, ctypes.byref(current), ctypes.byref(maximum)):
            return Unanswered(ctypes.get_last_error())
        match current.value:
            case 1 | 2 | 3 | 4 | 5 as value:
                return Power(value)
            case value:
                return Unrecognized(value)

    def set_power(self, monitor: Monitor, power: Power) -> Applied:
        """Every physical monitor behind `monitor` takes `power`; the first refusal is reported."""
        handles = self._handles.get(monitor, ())
        if not handles:
            return Detached()
        refused = tuple(ctypes.get_last_error() for handle in handles if not _SetVCPFeature(handle, _POWER_MODE, power.value))
        return Unanswered(refused[0]) if refused else power

    def close(self) -> None:
        for array in self._opened.get().arrays:
            DestroyPhysicalMonitors(len(array), array)
        self._opened.set(_Handles((), frozendict()))
