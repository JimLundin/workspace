# Consumed default-playback endpoint interfaces; generated COM methods return
# integer HRESULTs, rather than ctypes' generic function-pointer result union.
from win32more._win32 import ComPtr, Guid

eConsole: int  # noqa: N816 - native SDK enum constant spelling.
eRender: int  # noqa: N816 - native SDK enum constant spelling.
MMDeviceEnumerator: Guid

class IMMDevice(ComPtr):
    def Activate(self, interface_id: Guid, context: int, parameters: None, result: ComPtr) -> int: ...

class IMMDeviceEnumerator(ComPtr):
    def GetDefaultAudioEndpoint(self, flow: int, role: int, result: IMMDevice) -> int: ...
