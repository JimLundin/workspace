# The consumed mute observation writes a native BOOL through ctypes.byref and
# reports success or failure as the SDK's signed integer HRESULT.
from ctypes import _CArgObject

from win32more._win32 import ComPtr

class IAudioEndpointVolume(ComPtr):
    def GetMute(self, muted: _CArgObject) -> int: ...
