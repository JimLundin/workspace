"""Read-only default speaker mute and Wi-Fi association; no scans or connection changes."""
# pyright: reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnknownVariableType=false, reportMissingTypeStubs=false

import ctypes
from ctypes import wintypes

from assistant.ambient import Speakers, Wifi
from winapi._core import fn

_wlan = ctypes.WinDLL("wlanapi", use_last_error=True)
_WlanOpenHandle = fn(_wlan, "WlanOpenHandle", wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                     ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.HANDLE))
_WlanEnumInterfaces = fn(_wlan, "WlanEnumInterfaces", wintypes.DWORD, wintypes.HANDLE, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))
_WlanFreeMemory = fn(_wlan, "WlanFreeMemory", None, ctypes.c_void_p)
_WlanCloseHandle = fn(_wlan, "WlanCloseHandle", wintypes.DWORD, wintypes.HANDLE, ctypes.c_void_p)


class WlanInterface(ctypes.Structure):
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
    from win32more import FAILED  # noqa: PLC0415
    from win32more.Windows.Win32.Media.Audio import IMMDevice, IMMDeviceEnumerator, MMDeviceEnumerator, eConsole, eRender  # noqa: PLC0415
    from win32more.Windows.Win32.Media.Audio.Endpoints import IAudioEndpointVolume  # noqa: PLC0415
    from win32more.Windows.Win32.System.Com import (  # noqa: PLC0415
        CLSCTX_ALL,
        COINIT_MULTITHREADED,
        CoCreateInstance,
        CoInitializeEx,
        CoUninitialize,
    )

    if FAILED(CoInitializeEx(None, COINIT_MULTITHREADED)):
        return Speakers.UNKNOWN
    enumerator = IMMDeviceEnumerator(own=True)
    device = IMMDevice(own=True)
    volume = IAudioEndpointVolume(own=True)
    try:
        if FAILED(CoCreateInstance(MMDeviceEnumerator, None, CLSCTX_ALL, IMMDeviceEnumerator._iid_, enumerator)):  # pyright: ignore[reportPrivateUsage]
            return Speakers.UNKNOWN
        if FAILED(enumerator.GetDefaultAudioEndpoint(eRender, eConsole, device)):
            return Speakers.UNKNOWN
        if FAILED(device.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None, volume)):  # pyright: ignore[reportPrivateUsage]
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
