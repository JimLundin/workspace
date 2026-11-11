"""Default speaker mute and level, Wi-Fi association and the networks in range.

The writes are the speakers' level and mute, a scan for networks, and joining
one through the profile Windows saved for it; joining a new network is Windows' own.
"""

import ctypes
import math
from collections.abc import Generator
from contextlib import contextmanager
from ctypes import wintypes
from typing import Final

lazy from win32more import FAILED
lazy from win32more._win32 import Guid
lazy from win32more.Windows.Win32.Media.Audio import IMMDevice, IMMDeviceEnumerator, MMDeviceEnumerator, eConsole, eRender
lazy from win32more.Windows.Win32.Media.Audio.Endpoints import IAudioEndpointVolume
lazy from win32more.Windows.Win32.NetworkManagement.WiFi import (
    WLAN_API_VERSION_2_0,
    WLAN_AVAILABLE_NETWORK_CONNECTED,
    WLAN_AVAILABLE_NETWORK_LIST,
    WLAN_CONNECTION_PARAMETERS,
    WLAN_INTERFACE_INFO_LIST,
    WlanCloseHandle,
    WlanConnect,
    WlanEnumInterfaces,
    WlanFreeMemory,
    WlanGetAvailableNetworkList,
    WlanOpenHandle,
    WlanScan,
    dot11_BSS_type_infrastructure,
    wlan_connection_mode_profile,
)
lazy from win32more.Windows.Win32.System.Com import CLSCTX_ALL, COINIT_MULTITHREADED, CoCreateInstance, CoInitializeEx, CoUninitialize

from winapi.machine_status import LOCATION_OFF, Audio, Listing, Network, Speakers, Wifi, nearby


def wifi_state(states: tuple[int, ...]) -> Wifi:
    """One associated interface suffices; absent adapters and invalid observations aren't disconnect alerts."""
    if not states:
        return Wifi.NO_ADAPTER
    if any(state not in range(8) for state in states):
        return Wifi.UNKNOWN
    return Wifi.CONNECTED if any(state in (1, 2) for state in states) else Wifi.DISCONNECTED


def wifi() -> Wifi:
    handle, version, interfaces = ctypes.c_void_p(), ctypes.c_uint32(), ctypes.POINTER(WLAN_INTERFACE_INFO_LIST)()
    if WlanOpenHandle(WLAN_API_VERSION_2_0, None, ctypes.byref(version), ctypes.byref(handle)):
        return Wifi.UNKNOWN
    try:
        if WlanEnumInterfaces(handle, None, ctypes.byref(interfaces)) or not interfaces:
            return Wifi.UNKNOWN
        listed = interfaces.contents
        if not 0 <= listed.dwNumberOfItems <= 64:
            return Wifi.UNKNOWN
        return wifi_state(tuple(item.isState for item in listed.InterfaceInfo[: listed.dwNumberOfItems]))
    finally:
        if interfaces:
            WlanFreeMemory(interfaces)
        WlanCloseHandle(handle, None)


@contextmanager
def _adapters() -> Generator[tuple[ctypes.c_void_p, tuple[Guid, ...]]]:
    """A WLAN client handle and each Wi-Fi adapter's identity, valid inside the block; none when Windows offers none."""
    handle, version, interfaces = ctypes.c_void_p(), ctypes.c_uint32(), ctypes.POINTER(WLAN_INTERFACE_INFO_LIST)()
    if WlanOpenHandle(WLAN_API_VERSION_2_0, None, ctypes.byref(version), ctypes.byref(handle)):
        yield handle, ()
        return
    try:
        if WlanEnumInterfaces(handle, None, ctypes.byref(interfaces)) or not interfaces:
            yield handle, ()
            return
        listed = interfaces.contents
        count = listed.dwNumberOfItems if 0 <= listed.dwNumberOfItems <= 64 else 0
        yield handle, tuple(item.InterfaceGuid for item in listed.InterfaceInfo[:count])
    finally:
        if interfaces:
            WlanFreeMemory(interfaces)
        WlanCloseHandle(handle, None)


def scan() -> None:
    """Ask every adapter to look for networks; their lists refresh a few seconds later."""
    with _adapters() as (handle, guids):
        for guid in guids:
            WlanScan(handle, ctypes.byref(guid), None, None, None)


def _ssid(length: int, raw: bytes) -> str:
    return raw[: min(length, 32)].decode("utf-8", errors="replace")


ACCESS_DENIED: Final = 5
"""What Windows answers a list request while location services are off for desktop apps."""


def networks() -> Listing:
    """The networks every adapter hears, one per name, the connected one first."""
    with _adapters() as (handle, guids):
        heard = tuple(_heard(handle, guid) for guid in guids)
        if any(each is LOCATION_OFF for each in heard):
            return LOCATION_OFF
        return nearby(sighting for each in heard if each is not LOCATION_OFF for sighting in each)


def _heard(handle: ctypes.c_void_p, guid: Guid) -> Listing:
    listed = ctypes.POINTER(WLAN_AVAILABLE_NETWORK_LIST)()
    if (failed := WlanGetAvailableNetworkList(handle, ctypes.byref(guid), 0, None, ctypes.byref(listed))) or not listed:
        return LOCATION_OFF if failed == ACCESS_DENIED else ()
    try:
        found = listed.contents
        count = found.dwNumberOfItems if 0 <= found.dwNumberOfItems <= 1024 else 0
        return tuple(
            Network(
                _ssid(item.dot11Ssid.uSSIDLength, bytes(item.dot11Ssid.ucSSID)),
                min(100, max(0, item.wlanSignalQuality)),
                secured=bool(item.bSecurityEnabled),
                connected=bool(item.dwFlags & WLAN_AVAILABLE_NETWORK_CONNECTED),
                profile=item.strProfileName or None,
            )
            for item in found.Network[:count]
        )
    finally:
        WlanFreeMemory(listed)


def join(profile: str) -> bool:
    """Connect through the saved `profile` on the first adapter that accepts it; False when none does."""
    with _adapters() as (handle, guids):
        parameters = WLAN_CONNECTION_PARAMETERS()
        parameters.wlanConnectionMode = wlan_connection_mode_profile
        parameters.strProfile = profile
        parameters.dot11BssType = dot11_BSS_type_infrastructure
        return any(not WlanConnect(handle, ctypes.byref(guid), ctypes.byref(parameters), None) for guid in guids)


@contextmanager
def endpoint() -> Generator[IAudioEndpointVolume | None]:
    """The current default playback endpoint, resolved on each use so device changes are reflected."""
    if FAILED(CoInitializeEx(None, COINIT_MULTITHREADED)):
        yield None
        return
    enumerator = IMMDeviceEnumerator(own=True)
    device = IMMDevice(own=True)
    volume = IAudioEndpointVolume(own=True)
    try:
        # Published Windows interface IDs; avoid the binding's private metadata.
        enumerator_id = Guid("{a95664d2-9614-4f35-a746-de8db63617e6}")
        volume_id = Guid("{5cdf2c82-841e-4546-9722-0cf74078229a}")
        if (
            FAILED(CoCreateInstance(MMDeviceEnumerator, None, CLSCTX_ALL, enumerator_id, enumerator))
            or FAILED(enumerator.GetDefaultAudioEndpoint(eRender, eConsole, device))
            or FAILED(device.Activate(volume_id, CLSCTX_ALL, None, volume))
        ):
            yield None
        else:
            yield volume
    finally:
        del volume, device, enumerator
        CoUninitialize()


def audio() -> Audio:
    try:
        with endpoint() as volume:
            if volume is None:
                return Audio(Speakers.UNKNOWN, None)
            muted, level = wintypes.BOOL(), ctypes.c_float()
            if FAILED(volume.GetMute(ctypes.byref(muted))) or muted.value not in (0, 1):
                speakers = Speakers.UNKNOWN
            else:
                speakers = Speakers.MUTED if muted.value else Speakers.AUDIBLE
            read = not FAILED(volume.GetMasterVolumeLevelScalar(ctypes.byref(level)))
            return Audio(speakers, level.value if read and math.isfinite(level.value) and 0 <= level.value <= 1 else None)
    except OSError:
        return Audio(Speakers.UNKNOWN, None)


def set_volume(level: float) -> bool:
    """Set the default speakers' master level, from 0 to 1; False when Windows refuses it."""
    if not (math.isfinite(level) and 0 <= level <= 1):
        raise ValueError("A speaker level runs from 0 to 1.")
    try:
        with endpoint() as volume:
            return volume is not None and not FAILED(volume.SetMasterVolumeLevelScalar(level, None))
    except OSError:
        return False


def set_mute(*, muted: bool) -> bool:
    """Mute or unmute the default speakers; False when Windows refuses it."""
    try:
        with endpoint() as volume:
            return volume is not None and not FAILED(volume.SetMute(muted, None))
    except OSError:
        return False
