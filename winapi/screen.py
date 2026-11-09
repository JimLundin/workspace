"""Monitors, DPI awareness, and capturing the screen."""

import ctypes
from dataclasses import dataclass, field

lazy from win32more.Windows.Win32.Devices.Display import (
    DISPLAYCONFIG_DEVICE_INFO_GET_SOURCE_NAME,
    DISPLAYCONFIG_MODE_INFO,
    DISPLAYCONFIG_OUTPUT_TECHNOLOGY_DISPLAYPORT_EMBEDDED,
    DISPLAYCONFIG_OUTPUT_TECHNOLOGY_INTERNAL,
    DISPLAYCONFIG_OUTPUT_TECHNOLOGY_UDI_EMBEDDED,
    DISPLAYCONFIG_PATH_INFO,
    DISPLAYCONFIG_SOURCE_DEVICE_NAME,
    QDC_ONLY_ACTIVE_PATHS,
    DisplayConfigGetDeviceInfo,
    GetDisplayConfigBufferSizes,
    QueryDisplayConfig,
)
lazy from win32more.Windows.Win32.Foundation import ERROR_INSUFFICIENT_BUFFER
lazy from win32more.Windows.Win32.Graphics.Gdi import (
    BITMAPINFO,
    BITMAPINFOHEADER,
    CAPTUREBLT,
    DIB_RGB_COLORS,
    HALFTONE,
    MONITOR_DEFAULTTONEAREST,
    MONITORENUMPROC,
    MONITORINFOEXW,
    SRCCOPY,
    CreateCompatibleDC,
    CreateDIBSection,
    DeleteDC,
    EnumDisplayMonitors,
    GetDC,
    GetMonitorInfoW,
    MonitorFromWindow,
    ReleaseDC,
    SelectObject,
    SetBrushOrgEx,
    SetStretchBltMode,
    StretchBlt,
)
lazy from win32more.Windows.Win32.UI.HiDpi import DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2, SetProcessDpiAwarenessContext
lazy from win32more.Windows.Win32.UI.WindowsAndMessaging import MONITORINFOF_PRIMARY, SetProcessDPIAware

from winapi._core import DeleteObject
from winapi.shapes import Rect


@dataclass(frozen=True, slots=True)
class Monitor:
    area: Rect
    work: Rect
    """The area windows are placed in: without the taskbar."""
    primary: bool = field(kw_only=True)
    internal: bool = field(kw_only=True)
    """The laptop's own panel, as the display configuration reports its connection."""


def top_down(width: int, height: int) -> BITMAPINFO:
    """A 32-bit device-independent bitmap's header, top row first."""
    header = BITMAPINFOHEADER(biSize=ctypes.sizeof(BITMAPINFOHEADER), biWidth=width, biHeight=-height, biPlanes=1, biBitCount=32)
    return BITMAPINFO(bmiHeader=header)


def use_physical_pixels() -> None:
    """Makes every coordinate this process sees a real pixel, on every monitor.
    Call before creating any window."""
    if not SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2):
        SetProcessDPIAware()


def built_in_devices() -> frozenset[str]:
    """The GDI device names of the active displays driven by a built-in panel connection."""
    for _attempt in range(3):  # The configuration can change between sizing and querying.
        paths, modes = ctypes.c_uint32(), ctypes.c_uint32()
        if GetDisplayConfigBufferSizes(QDC_ONLY_ACTIVE_PATHS, ctypes.byref(paths), ctypes.byref(modes)):
            return frozenset()
        path_info = (DISPLAYCONFIG_PATH_INFO * paths.value)()
        mode_info = (DISPLAYCONFIG_MODE_INFO * modes.value)()
        result = QueryDisplayConfig(QDC_ONLY_ACTIVE_PATHS, ctypes.byref(paths), path_info, ctypes.byref(modes), mode_info, None)
        if result == ERROR_INSUFFICIENT_BUFFER:
            continue
        if result:
            return frozenset()
        return frozenset(name for path in path_info[: paths.value] if (name := _source_name(path)) is not None)
    return frozenset()


def _source_name(path: DISPLAYCONFIG_PATH_INFO) -> str | None:
    built_in = (
        DISPLAYCONFIG_OUTPUT_TECHNOLOGY_INTERNAL,
        DISPLAYCONFIG_OUTPUT_TECHNOLOGY_DISPLAYPORT_EMBEDDED,
        DISPLAYCONFIG_OUTPUT_TECHNOLOGY_UDI_EMBEDDED,
    )
    if path.targetInfo.outputTechnology not in built_in:
        return None
    name = DISPLAYCONFIG_SOURCE_DEVICE_NAME()
    name.header.type = DISPLAYCONFIG_DEVICE_INFO_GET_SOURCE_NAME
    name.header.size = ctypes.sizeof(DISPLAYCONFIG_SOURCE_DEVICE_NAME)
    name.header.adapterId = path.sourceInfo.adapterId
    name.header.id = path.sourceInfo.id
    # The header opens the request, so its address is the whole request's.
    return str(name.viewGdiDeviceName) if DisplayConfigGetDeviceInfo(name.header) == 0 else None


def _monitor(handle: int, built_in: frozenset[str]) -> Monitor:
    info = MONITORINFOEXW()
    info.monitorInfo.cbSize = ctypes.sizeof(MONITORINFOEXW)
    # The base fields open the extended structure, so their address is the whole structure's.
    GetMonitorInfoW(handle, info.monitorInfo)
    primary, internal = bool(info.monitorInfo.dwFlags & MONITORINFOF_PRIMARY), str(info.szDevice) in built_in
    area, work = info.monitorInfo.rcMonitor, info.monitorInfo.rcWork
    return Monitor(
        Rect(area.left, area.top, area.right, area.bottom), Rect(work.left, work.top, work.right, work.bottom), primary=primary, internal=internal
    )


def attached() -> tuple[tuple[int, Monitor], ...]:
    """Each monitor's HMONITOR and what Windows reports of it, in enumeration order."""
    found: list[tuple[int, Monitor]] = []
    built_in = built_in_devices()

    def each(handle: int, _dc: int | None, _rect: object, _data: int) -> bool:
        found.append((handle, _monitor(handle, built_in)))
        return True

    EnumDisplayMonitors(None, None, MONITORENUMPROC(each), 0)
    return tuple(found)


def monitors() -> list[Monitor]:
    """All monitors, left to right."""
    return sorted((monitor for _handle, monitor in attached()), key=lambda monitor: (monitor.area.left, monitor.area.top))


def monitor_of(hwnd: int) -> Monitor:
    handle = MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
    if handle is None:
        raise OSError("Windows reports no monitor near the window.")
    return _monitor(handle, built_in_devices())


def capture(area: Rect, width: int, height: int) -> bytes:
    """The pixels in `area`, scaled to width x height: BGRA, top row first."""
    header = top_down(width, height)
    screen = GetDC(None)
    memory = CreateCompatibleDC(screen)
    bits = ctypes.c_void_p()
    bitmap = CreateDIBSection(memory, header, DIB_RGB_COLORS, ctypes.byref(bits), None, 0)
    previous = SelectObject(memory, bitmap)
    try:
        SetStretchBltMode(memory, HALFTONE)  # averages pixels when shrinking, so text stays legible
        SetBrushOrgEx(memory, 0, 0, None)
        StretchBlt(memory, 0, 0, width, height, screen, area.left, area.top, area.width, area.height, SRCCOPY | CAPTUREBLT)
        return ctypes.string_at(bits, width * height * 4)
    finally:
        SelectObject(memory, previous)
        DeleteObject(bitmap)
        DeleteDC(memory)
        ReleaseDC(None, screen)
