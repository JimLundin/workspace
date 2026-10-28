# The consumed mute observation writes a native BOOL through ctypes.byref and
# reports success or failure as the SDK's signed integer HRESULT.
from ctypes import wintypes

from win32more._win32 import ByReference, ComPtr

class IAudioEndpointVolume(ComPtr):
    def GetMute(self, muted: ByReference[wintypes.BOOL]) -> int: ...
