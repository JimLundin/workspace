# Consumed interface enumeration. Results are Win32 error codes; the interface list is
# Windows-owned until WlanFreeMemory, and its array holds `dwNumberOfItems` entries.
import ctypes
from typing import type_check_only

from win32more._win32 import ByReference, OutputPointer

WLAN_API_VERSION_2_0: int

class WLAN_INTERFACE_INFO(ctypes.Structure):
    isState: int

@type_check_only
class _Interfaces:
    def __getitem__(self, index: slice[None, int, None], /) -> list[WLAN_INTERFACE_INFO]: ...

class WLAN_INTERFACE_INFO_LIST(ctypes.Structure):
    dwNumberOfItems: int
    InterfaceInfo: _Interfaces

def WlanOpenHandle(version: int, reserved: None, negotiated: ByReference[ctypes.c_uint32], handle: ByReference[ctypes.c_void_p]) -> int: ...
def WlanEnumInterfaces(handle: ctypes.c_void_p, reserved: None, interfaces: ByReference[OutputPointer[WLAN_INTERFACE_INFO_LIST]]) -> int: ...
def WlanFreeMemory(memory: OutputPointer[WLAN_INTERFACE_INFO_LIST]) -> None: ...
def WlanCloseHandle(handle: ctypes.c_void_p, reserved: None) -> int: ...
