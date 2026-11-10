# Consumed GDI and monitor calls. Handles are pointer-sized integers, None when null;
# structures pass by reference and BOOL results are ints.
import ctypes
from collections.abc import Callable
from typing import type_check_only

from win32more._win32 import ByReference
from win32more.Windows.Win32.Foundation import POINT, RECT

CAPTUREBLT: int
CLR_INVALID: int
COLOR_WINDOW: int
COLOR_WINDOWTEXT: int
DIB_RGB_COLORS: int
HALFTONE: int
MONITOR_DEFAULTTONEAREST: int
SRCCOPY: int

class BITMAPINFOHEADER(ctypes.Structure):
    def __init__(self, *, biSize: int, biWidth: int, biHeight: int, biPlanes: int, biBitCount: int) -> None: ...

class BITMAPINFO(ctypes.Structure):
    def __init__(self, *, bmiHeader: BITMAPINFOHEADER) -> None: ...

class BITMAP(ctypes.Structure):
    bmWidth: int

@type_check_only
class _MonitorInfo(ctypes.Structure):
    cbSize: int
    rcMonitor: RECT
    rcWork: RECT
    dwFlags: int

class MONITORINFOEXW(ctypes.Structure):
    monitorInfo: _MonitorInfo
    szDevice: str

class MONITORENUMPROC:
    def __init__(self, callback: Callable[[int, int | None, object, int], bool], /) -> None: ...

def GetDC(hwnd: None) -> int | None: ...
def ReleaseDC(hwnd: None, dc: int | None) -> int: ...
def CreateCompatibleDC(dc: int | None) -> int | None: ...
def DeleteDC(dc: int | None) -> int: ...
def SelectObject(dc: int | None, object: int | None) -> int | None: ...
def CreateDIBSection(dc: int | None, info: BITMAPINFO, usage: int, bits: ByReference[ctypes.c_void_p], section: None, offset: int) -> int | None: ...
def CreateBitmap(width: int, height: int, planes: int, bits_per_pixel: int, bits: ctypes.Array[ctypes.c_char]) -> int | None: ...
def GetObjectW(object: int, size: int, buffer: ByReference[BITMAP]) -> int: ...
def GetPixel(dc: int, x: int, y: int) -> int: ...
def GetSysColor(index: int) -> int: ...
def SetStretchBltMode(dc: int | None, mode: int) -> int: ...
def SetBrushOrgEx(dc: int | None, x: int, y: int, previous: None) -> int: ...
def StretchBlt(
    target: int | None,
    x: int,
    y: int,
    width: int,
    height: int,
    source: int | None,
    source_x: int,
    source_y: int,
    source_width: int,
    source_height: int,
    operation: int,
) -> int: ...
def EnumDisplayMonitors(dc: None, clip: None, callback: MONITORENUMPROC, data: int) -> int: ...
def GetMonitorInfoW(monitor: int, info: _MonitorInfo) -> int: ...
def MonitorFromWindow(hwnd: int, flags: int) -> int | None: ...
def ClientToScreen(hwnd: int, point: ByReference[POINT]) -> int: ...
