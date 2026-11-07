"""Monitors, DPI awareness, and capturing the screen."""

import ctypes
from ctypes import wintypes
from dataclasses import dataclass, field
from typing import Final

from winapi._core import fn, gdi32, last_error, optional_fn, rect, user32
from winapi.shapes import Rect


class MONITORINFOEXW(ctypes.Structure):
    cbSize: int
    rcMonitor: wintypes.RECT
    rcWork: wintypes.RECT
    dwFlags: int
    szDevice: str
    _fields_ = (
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
        ("szDevice", wintypes.WCHAR * 32),
    )


class LUID(ctypes.Structure):
    _fields_ = (("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG))


class DisplayPathSource(ctypes.Structure):
    adapterId: LUID
    id: int
    _fields_ = (("adapterId", LUID), ("id", ctypes.c_uint32), ("modeInfoIdx", ctypes.c_uint32), ("statusFlags", ctypes.c_uint32))


class DisplayPathTarget(ctypes.Structure):
    outputTechnology: int
    _fields_ = (
        ("adapterId", LUID),
        ("id", ctypes.c_uint32),
        ("modeInfoIdx", ctypes.c_uint32),
        ("outputTechnology", ctypes.c_uint32),
        ("rotation", ctypes.c_uint32),
        ("scaling", ctypes.c_uint32),
        ("refreshRate", ctypes.c_uint32 * 2),
        ("scanLineOrdering", ctypes.c_uint32),
        ("targetAvailable", wintypes.BOOL),
        ("statusFlags", ctypes.c_uint32),
    )


class DisplayPath(ctypes.Structure):
    sourceInfo: DisplayPathSource
    targetInfo: DisplayPathTarget
    _fields_ = (("sourceInfo", DisplayPathSource), ("targetInfo", DisplayPathTarget), ("flags", ctypes.c_uint32))


class DisplayMode(ctypes.Structure):
    _fields_ = (("infoType", ctypes.c_uint32), ("id", ctypes.c_uint32), ("adapterId", LUID), ("mode", ctypes.c_byte * 48))


class DisplayInfoHeader(ctypes.Structure):
    type: int
    size: int
    adapterId: LUID
    id: int
    _fields_ = (("type", ctypes.c_uint32), ("size", ctypes.c_uint32), ("adapterId", LUID), ("id", ctypes.c_uint32))


class DisplaySourceName(ctypes.Structure):
    header: DisplayInfoHeader
    viewGdiDeviceName: str
    _fields_ = (("header", DisplayInfoHeader), ("viewGdiDeviceName", wintypes.WCHAR * 32))


class BITMAPINFOHEADER(ctypes.Structure):
    biSize: int
    biWidth: int
    biHeight: int
    biPlanes: int
    biBitCount: int
    biCompression: int
    biSizeImage: int
    biXPelsPerMeter: int
    biYPelsPerMeter: int
    biClrUsed: int
    biClrImportant: int
    _fields_ = (
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    )


class BITMAPINFO(ctypes.Structure):
    bmiHeader: BITMAPINFOHEADER
    bmiColors: ctypes.Array[ctypes.c_ulong]
    _fields_ = (("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3))


MONITORENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)
_EnumDisplayMonitors = fn(user32, "EnumDisplayMonitors", wintypes.BOOL, wintypes.HDC, ctypes.c_void_p, MONITORENUMPROC, wintypes.LPARAM)
_GetMonitorInfoW = fn(user32, "GetMonitorInfoW", wintypes.BOOL, wintypes.HMONITOR, ctypes.POINTER(MONITORINFOEXW))
_GetDisplayConfigBufferSizes = fn(
    user32, "GetDisplayConfigBufferSizes", ctypes.c_long, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ctypes.c_uint32)
)
_QueryDisplayConfig = fn(
    user32,
    "QueryDisplayConfig",
    ctypes.c_long,
    ctypes.c_uint32,
    ctypes.POINTER(ctypes.c_uint32),
    ctypes.POINTER(DisplayPath),
    ctypes.POINTER(ctypes.c_uint32),
    ctypes.POINTER(DisplayMode),
    ctypes.c_void_p,
)
_DisplayConfigGetDeviceInfo = fn(user32, "DisplayConfigGetDeviceInfo", ctypes.c_long, ctypes.POINTER(DisplaySourceName))
_MonitorFromWindow = fn(user32, "MonitorFromWindow", wintypes.HMONITOR, wintypes.HWND, wintypes.DWORD)
_GetSystemMetrics = fn(user32, "GetSystemMetrics", ctypes.c_int, ctypes.c_int)
_SetProcessDpiAwarenessContext = optional_fn(user32, "SetProcessDpiAwarenessContext", wintypes.BOOL, ctypes.c_ssize_t)
_SetProcessDPIAware = fn(user32, "SetProcessDPIAware", wintypes.BOOL)
_GetDC = fn(user32, "GetDC", wintypes.HDC, wintypes.HWND)
_ReleaseDC = fn(user32, "ReleaseDC", ctypes.c_int, wintypes.HWND, wintypes.HDC)
_CreateCompatibleDC = fn(gdi32, "CreateCompatibleDC", wintypes.HDC, wintypes.HDC)
_DeleteDC = fn(gdi32, "DeleteDC", wintypes.BOOL, wintypes.HDC)
_CreateDIBSection = fn(
    gdi32,
    "CreateDIBSection",
    wintypes.HBITMAP,
    wintypes.HDC,
    ctypes.POINTER(BITMAPINFO),
    wintypes.UINT,
    ctypes.POINTER(ctypes.c_void_p),
    wintypes.HANDLE,
    wintypes.DWORD,
)
_SelectObject = fn(gdi32, "SelectObject", wintypes.HGDIOBJ, wintypes.HDC, wintypes.HGDIOBJ)
_DeleteObject = fn(gdi32, "DeleteObject", wintypes.BOOL, wintypes.HGDIOBJ)
_SetStretchBltMode = fn(gdi32, "SetStretchBltMode", ctypes.c_int, wintypes.HDC, ctypes.c_int)
_SetBrushOrgEx = fn(gdi32, "SetBrushOrgEx", wintypes.BOOL, wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_void_p)
_StretchBlt = fn(
    gdi32,
    "StretchBlt",
    wintypes.BOOL,
    wintypes.HDC,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.HDC,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.DWORD,
)

_SM_XVIRTUALSCREEN, _SM_YVIRTUALSCREEN, _SM_CXVIRTUALSCREEN, _SM_CYVIRTUALSCREEN = 76, 77, 78, 79
_MONITORINFOF_PRIMARY: Final = 1
_QDC_ONLY_ACTIVE_PATHS: Final = 2
_DISPLAYCONFIG_DEVICE_INFO_GET_SOURCE_NAME: Final = 1
_ERROR_INSUFFICIENT_BUFFER: Final = 122
# Built-in panels: DISPLAYCONFIG_OUTPUT_TECHNOLOGY_INTERNAL, DISPLAYPORT_EMBEDDED and UDI_EMBEDDED.
_BUILT_IN: Final = frozenset({0x8000_0000, 11, 13})
_MONITOR_DEFAULTTONEAREST: Final = 2
_PER_MONITOR_AWARE_V2: Final = -4
_DIB_RGB_COLORS, _HALFTONE = 0, 4
_SRCCOPY, _CAPTUREBLT = 0x00CC_0020, 0x4000_0000


@dataclass(frozen=True, slots=True)
class Monitor:
    area: Rect
    work: Rect
    """The area windows are placed in: without the taskbar."""
    primary: bool = field(kw_only=True)
    internal: bool = field(kw_only=True)
    """The laptop's own panel, as the display configuration reports its connection."""


def use_physical_pixels() -> None:
    """Makes every coordinate this process sees a real pixel, on every monitor.
    Call before creating any window."""
    if _SetProcessDpiAwarenessContext is None or not _SetProcessDpiAwarenessContext(_PER_MONITOR_AWARE_V2):
        _SetProcessDPIAware()


def virtual_screen() -> Rect:
    """The rectangle around all monitors."""
    left, top = int(_GetSystemMetrics(_SM_XVIRTUALSCREEN)), int(_GetSystemMetrics(_SM_YVIRTUALSCREEN))
    return Rect(left, top, left + int(_GetSystemMetrics(_SM_CXVIRTUALSCREEN)), top + int(_GetSystemMetrics(_SM_CYVIRTUALSCREEN)))


def built_in_devices() -> frozenset[str]:
    """The GDI device names of the active displays driven by a built-in panel connection."""
    for _attempt in range(3):  # The configuration can change between sizing and querying.
        paths, modes = ctypes.c_uint32(), ctypes.c_uint32()
        if _GetDisplayConfigBufferSizes(_QDC_ONLY_ACTIVE_PATHS, ctypes.byref(paths), ctypes.byref(modes)):
            return frozenset()
        path_info = (DisplayPath * paths.value)()
        mode_info = (DisplayMode * modes.value)()
        result = _QueryDisplayConfig(_QDC_ONLY_ACTIVE_PATHS, ctypes.byref(paths), path_info, ctypes.byref(modes), mode_info, None)
        if result == _ERROR_INSUFFICIENT_BUFFER:
            continue
        if result:
            return frozenset()
        return frozenset(name for path in path_info[: paths.value] if (name := _source_name(path)) is not None)
    return frozenset()


def _source_name(path: DisplayPath) -> str | None:
    if path.targetInfo.outputTechnology not in _BUILT_IN:
        return None
    name = DisplaySourceName()
    name.header.type = _DISPLAYCONFIG_DEVICE_INFO_GET_SOURCE_NAME
    name.header.size = ctypes.sizeof(DisplaySourceName)
    name.header.adapterId = path.sourceInfo.adapterId
    name.header.id = path.sourceInfo.id
    return str(name.viewGdiDeviceName) if _DisplayConfigGetDeviceInfo(ctypes.byref(name)) == 0 else None


def _monitor(handle: int, built_in: frozenset[str]) -> Monitor:
    info = MONITORINFOEXW()
    info.cbSize = ctypes.sizeof(MONITORINFOEXW)
    _GetMonitorInfoW(handle, ctypes.byref(info))
    primary, internal = bool(info.dwFlags & _MONITORINFOF_PRIMARY), str(info.szDevice) in built_in
    return Monitor(rect(info.rcMonitor), rect(info.rcWork), primary=primary, internal=internal)


def attached() -> tuple[tuple[int, Monitor], ...]:
    """Each monitor's HMONITOR and what Windows reports of it, in enumeration order."""
    found: list[tuple[int, Monitor]] = []
    built_in = built_in_devices()

    def each(handle: int, _dc: int, _rect: object, _data: int) -> bool:
        found.append((handle, _monitor(handle, built_in)))
        return True

    _EnumDisplayMonitors(None, None, MONITORENUMPROC(each), 0)
    return tuple(found)


def monitors() -> list[Monitor]:
    """All monitors, left to right."""
    return sorted((monitor for _handle, monitor in attached()), key=lambda monitor: (monitor.area.left, monitor.area.top))


def monitor_of(hwnd: int) -> Monitor:
    handle = _MonitorFromWindow(hwnd, _MONITOR_DEFAULTTONEAREST)
    if handle is None:
        raise last_error()
    return _monitor(handle, built_in_devices())


def capture(area: Rect, width: int, height: int) -> bytes:
    """The pixels in `area`, scaled to width x height: BGRA, top row first."""
    info = BITMAPINFO()
    info.bmiHeader = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), width, -height, 1, 32, 0, 0, 0, 0, 0, 0)
    screen = _GetDC(None)
    memory = _CreateCompatibleDC(screen)
    bits = ctypes.c_void_p()
    bitmap = _CreateDIBSection(memory, ctypes.byref(info), _DIB_RGB_COLORS, ctypes.byref(bits), None, 0)
    previous = _SelectObject(memory, bitmap)
    try:
        _SetStretchBltMode(memory, _HALFTONE)  # averages pixels when shrinking, so text stays legible
        _SetBrushOrgEx(memory, 0, 0, None)
        _StretchBlt(memory, 0, 0, width, height, screen, area.left, area.top, area.width, area.height, _SRCCOPY | _CAPTUREBLT)
        return ctypes.string_at(bits, width * height * 4)
    finally:
        _SelectObject(memory, previous)
        _DeleteObject(bitmap)
        _DeleteDC(memory)
        _ReleaseDC(None, screen)
