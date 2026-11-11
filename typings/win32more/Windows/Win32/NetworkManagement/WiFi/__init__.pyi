# Consumed interface enumeration, network listing, scanning and joining by profile.
# Results are Win32 error codes; each list is Windows-owned until WlanFreeMemory, and
# its array holds `dwNumberOfItems` entries.
import ctypes
from typing import type_check_only

from win32more._win32 import ByReference, Guid, OutputPointer

WLAN_API_VERSION_2_0: int
WLAN_AVAILABLE_NETWORK_CONNECTED: int
dot11_BSS_type_infrastructure: int  # noqa: N816 - the SDK's name
wlan_connection_mode_profile: int

class WLAN_INTERFACE_INFO(ctypes.Structure):
    InterfaceGuid: Guid
    isState: int

@type_check_only
class _Interfaces:
    def __getitem__(self, index: slice[None, int, None], /) -> list[WLAN_INTERFACE_INFO]: ...

class WLAN_INTERFACE_INFO_LIST(ctypes.Structure):
    dwNumberOfItems: int
    InterfaceInfo: _Interfaces

def WlanOpenHandle(version: int, reserved: None, negotiated: ByReference[ctypes.c_uint32], handle: ByReference[ctypes.c_void_p]) -> int: ...
def WlanEnumInterfaces(handle: ctypes.c_void_p, reserved: None, interfaces: ByReference[OutputPointer[WLAN_INTERFACE_INFO_LIST]]) -> int: ...

class DOT11_SSID(ctypes.Structure):
    uSSIDLength: int
    ucSSID: ctypes.Array[ctypes.c_ubyte]

class WLAN_AVAILABLE_NETWORK(ctypes.Structure):
    strProfileName: str
    dot11Ssid: DOT11_SSID
    wlanSignalQuality: int
    bSecurityEnabled: int
    dwFlags: int

@type_check_only
class _Networks:
    def __getitem__(self, index: slice[None, int, None], /) -> list[WLAN_AVAILABLE_NETWORK]: ...

class WLAN_AVAILABLE_NETWORK_LIST(ctypes.Structure):
    dwNumberOfItems: int
    Network: _Networks

class WLAN_CONNECTION_PARAMETERS(ctypes.Structure):
    wlanConnectionMode: int
    strProfile: str
    dot11BssType: int

def WlanFreeMemory(memory: OutputPointer[WLAN_INTERFACE_INFO_LIST] | OutputPointer[WLAN_AVAILABLE_NETWORK_LIST]) -> None: ...
def WlanScan(handle: ctypes.c_void_p, interface: ByReference[Guid], ssid: None, data: None, reserved: None) -> int: ...
def WlanGetAvailableNetworkList(
    handle: ctypes.c_void_p,
    interface: ByReference[Guid],
    flags: int,
    reserved: None,
    networks: ByReference[OutputPointer[WLAN_AVAILABLE_NETWORK_LIST]],
) -> int: ...
def WlanConnect(
    handle: ctypes.c_void_p, interface: ByReference[Guid], parameters: ByReference[WLAN_CONNECTION_PARAMETERS], reserved: None
) -> int: ...
def WlanCloseHandle(handle: ctypes.c_void_p, reserved: None) -> int: ...
