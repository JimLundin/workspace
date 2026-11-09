# Consumed input observation. The structure passes by reference; the BOOL result is an int.
import ctypes

class LASTINPUTINFO(ctypes.Structure):
    dwTime: int
    def __init__(self, *, cbSize: int) -> None: ...

def GetLastInputInfo(info: LASTINPUTINFO) -> int: ...
