"""Read-only default speaker mute and Wi-Fi association; no scans or connection changes."""

import ctypes
from ctypes import wintypes

lazy from win32more import FAILED
lazy from win32more._win32 import Guid
lazy from win32more.Windows.Win32.Media.Audio import IMMDevice, IMMDeviceEnumerator, MMDeviceEnumerator, eConsole, eRender
lazy from win32more.Windows.Win32.Media.Audio.Endpoints import IAudioEndpointVolume
lazy from win32more.Windows.Win32.System.Com import CLSCTX_ALL, COINIT_MULTITHREADED, CoCreateInstance, CoInitializeEx, CoUninitialize

from winapi._core import fn
from winapi.machine_status import Speakers, Wifi

_wlan = ctypes.WinDLL("wlanapi", use_last_error=True)
_WlanOpenHandle = fn(
    _wlan, "WlanOpenHandle", wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.HANDLE)
)
_WlanEnumInterfaces = fn(_wlan, "WlanEnumInterfaces", wintypes.DWORD, wintypes.HANDLE, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))
_WlanFreeMemory = fn(_wlan, "WlanFreeMemory", None, ctypes.c_void_p)
_WlanCloseHandle = fn(_wlan, "WlanCloseHandle", wintypes.DWORD, wintypes.HANDLE, ctypes.c_void_p)


class WlanInterface(ctypes.Structure):
    guid: ctypes.Array[ctypes.c_byte]
    description: str
    state: int
    _fields_ = (("guid", ctypes.c_byte * 16), ("description", ctypes.c_wchar * 256), ("state", wintypes.DWORD))


def wifi_state(states: tuple[int, ...]) -> Wifi:
    """One associated interface suffices; absent adapters and invalid observations aren't disconnect alerts."""
    if not states:
        return Wifi.NO_ADAPTER
    if any(state not in range(8) for state in states):
        return Wifi.UNKNOWN
    return Wifi.CONNECTED if any(state in (1, 2) for state in states) else Wifi.DISCONNECTED


def wifi() -> Wifi:
    handle, version, data = wintypes.HANDLE(), wintypes.DWORD(), ctypes.c_void_p()
    if _WlanOpenHandle(2, None, ctypes.byref(version), ctypes.byref(handle)):
        return Wifi.UNKNOWN
    try:
        if _WlanEnumInterfaces(handle, None, ctypes.byref(data)) or not data.value:
            return Wifi.UNKNOWN
        count = int(ctypes.cast(data, ctypes.POINTER(wintypes.DWORD)).contents.value)
        if not 0 <= count <= 64:
            return Wifi.UNKNOWN
        address = data.value + 8  # count and current-index DWORDs precede the variable interface array.
        interfaces = (WlanInterface * count).from_address(address)
        return wifi_state(tuple(int(item.state) for item in interfaces))
    finally:
        if data.value:
            _WlanFreeMemory(data)
        _WlanCloseHandle(handle, None)


def speakers() -> Speakers:
    """Resolve the current default playback endpoint on each observation, so device changes are reflected."""
    if FAILED(CoInitializeEx(None, COINIT_MULTITHREADED)):
        return Speakers.UNKNOWN
    enumerator = IMMDeviceEnumerator(own=True)
    device = IMMDevice(own=True)
    volume = IAudioEndpointVolume(own=True)
    try:
        # Published Windows interface IDs; avoid the binding's private metadata.
        enumerator_id = Guid("{a95664d2-9614-4f35-a746-de8db63617e6}")
        volume_id = Guid("{5cdf2c82-841e-4546-9722-0cf74078229a}")
        if FAILED(CoCreateInstance(MMDeviceEnumerator, None, CLSCTX_ALL, enumerator_id, enumerator)):
            return Speakers.UNKNOWN
        if FAILED(enumerator.GetDefaultAudioEndpoint(eRender, eConsole, device)):
            return Speakers.UNKNOWN
        if FAILED(device.Activate(volume_id, CLSCTX_ALL, None, volume)):
            return Speakers.UNKNOWN
        muted = wintypes.BOOL()
        if FAILED(volume.GetMute(ctypes.byref(muted))) or muted.value not in (0, 1):
            return Speakers.UNKNOWN
        return Speakers.MUTED if muted.value else Speakers.AUDIBLE
    except OSError:
        return Speakers.UNKNOWN
    finally:
        del volume, device, enumerator
        CoUninitialize()
