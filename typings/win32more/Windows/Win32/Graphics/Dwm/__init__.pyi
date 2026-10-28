import ctypes

from win32more._win32 import ByReference

def DwmSetWindowAttribute(hwnd: int, attribute: int, value: ByReference[ctypes.c_int | ctypes.c_uint32], size: int) -> int: ...
