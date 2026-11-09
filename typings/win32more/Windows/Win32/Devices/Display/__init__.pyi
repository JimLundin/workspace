# Consumed physical-monitor enumeration. Arrays and counts pass by reference; BOOL results are ints.
import ctypes
from typing import type_check_only

from win32more._win32 import ByReference

class PHYSICAL_MONITOR(ctypes.Structure):
    hPhysicalMonitor: int | None

def GetNumberOfPhysicalMonitorsFromHMONITOR(monitor: int, count: ByReference[ctypes.c_uint32]) -> int: ...
def GetPhysicalMonitorsFromHMONITOR(monitor: int, count: int, monitors: ctypes.Array[PHYSICAL_MONITOR]) -> int: ...
def DestroyPhysicalMonitors(count: int, monitors: ctypes.Array[PHYSICAL_MONITOR]) -> int: ...

DISPLAYCONFIG_DEVICE_INFO_GET_SOURCE_NAME: int
DISPLAYCONFIG_OUTPUT_TECHNOLOGY_DISPLAYPORT_EMBEDDED: int
DISPLAYCONFIG_OUTPUT_TECHNOLOGY_INTERNAL: int
DISPLAYCONFIG_OUTPUT_TECHNOLOGY_UDI_EMBEDDED: int
QDC_ONLY_ACTIVE_PATHS: int

class LUID(ctypes.Structure): ...

@type_check_only
class _Source(ctypes.Structure):
    adapterId: LUID
    id: int

@type_check_only
class _Target(ctypes.Structure):
    outputTechnology: int

class DISPLAYCONFIG_PATH_INFO(ctypes.Structure):
    sourceInfo: _Source
    targetInfo: _Target

class DISPLAYCONFIG_MODE_INFO(ctypes.Structure): ...

@type_check_only
class _Header(ctypes.Structure):
    type: int
    size: int
    adapterId: LUID
    id: int

class DISPLAYCONFIG_SOURCE_DEVICE_NAME(ctypes.Structure):
    header: _Header
    viewGdiDeviceName: str

def GetDisplayConfigBufferSizes(flags: int, paths: ByReference[ctypes.c_uint32], modes: ByReference[ctypes.c_uint32]) -> int: ...
def QueryDisplayConfig(
    flags: int,
    path_count: ByReference[ctypes.c_uint32],
    paths: ctypes.Array[DISPLAYCONFIG_PATH_INFO],
    mode_count: ByReference[ctypes.c_uint32],
    modes: ctypes.Array[DISPLAYCONFIG_MODE_INFO],
    topology: None,
) -> int: ...
def DisplayConfigGetDeviceInfo(request: _Header) -> int: ...
