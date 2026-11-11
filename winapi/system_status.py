"""Default speaker mute and level, and Wi-Fi association. The speakers' level and mute are the writes; no scans or connection changes."""

import ctypes
import math
from collections.abc import Generator
from contextlib import contextmanager
from ctypes import wintypes

lazy from win32more import FAILED
lazy from win32more._win32 import Guid
lazy from win32more.Windows.Win32.Media.Audio import IMMDevice, IMMDeviceEnumerator, MMDeviceEnumerator, eConsole, eRender
lazy from win32more.Windows.Win32.Media.Audio.Endpoints import IAudioEndpointVolume
lazy from win32more.Windows.Win32.NetworkManagement.WiFi import (
    WLAN_API_VERSION_2_0,
    WLAN_INTERFACE_INFO_LIST,
    WlanCloseHandle,
    WlanEnumInterfaces,
    WlanFreeMemory,
    WlanOpenHandle,
)
lazy from win32more.Windows.Win32.System.Com import CLSCTX_ALL, COINIT_MULTITHREADED, CoCreateInstance, CoInitializeEx, CoUninitialize

from winapi.machine_status import Audio, Speakers, Wifi


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
