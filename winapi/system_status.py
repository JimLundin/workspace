"""Default speaker mute and level. The speaker level is the one write."""

import ctypes
import math
from collections.abc import Generator
from contextlib import contextmanager
from ctypes import wintypes

lazy from win32more import FAILED
lazy from win32more._win32 import Guid
lazy from win32more.Windows.Win32.Media.Audio import IMMDevice, IMMDeviceEnumerator, MMDeviceEnumerator, eConsole, eRender
lazy from win32more.Windows.Win32.Media.Audio.Endpoints import IAudioEndpointVolume
lazy from win32more.Windows.Win32.System.Com import CLSCTX_ALL, COINIT_MULTITHREADED, CoCreateInstance, CoInitializeEx, CoUninitialize

from winapi.machine_status import Audio, Speakers


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
