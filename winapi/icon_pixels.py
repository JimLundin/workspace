"""Copy borrowed Windows icons into immutable pixels before their owners release them."""

import ctypes
from dataclasses import dataclass

lazy from win32more.Windows.Win32.Graphics.Gdi import BITMAP, DIB_RGB_COLORS, CreateCompatibleDC, CreateDIBSection, DeleteDC, GetObjectW, SelectObject
lazy from win32more.Windows.Win32.UI.WindowsAndMessaging import (
    DI_NORMAL,
    GCLP_HICON,
    GCLP_HICONSM,
    ICON_BIG,
    ICON_SMALL,
    ICON_SMALL2,
    ICONINFO,
    SMTO_ABORTIFHUNG,
    WM_GETICON,
    DrawIconEx,
    GetClassLongPtrW,
    GetIconInfo,
    SendMessageTimeoutW,
)

from winapi._core import DeleteObject
from winapi.screen import top_down


@dataclass(frozen=True, slots=True)
class Pixels:
    size: int
    bgra: bytes


def pixels(handle: int, size: int = 32) -> Pixels | None:
    """The adapter owns and releases its temporary DC/bitmap; the HICON is borrowed."""
    if not handle:
        return None
    dc = CreateCompatibleDC(None)
    if not dc:
        return None
    bits = ctypes.c_void_p()
    header = top_down(size, size)
    bitmap = CreateDIBSection(dc, header, DIB_RGB_COLORS, ctypes.byref(bits), None, 0)
    try:
        if not bitmap:
            return None
        previous = SelectObject(dc, bitmap)
        try:
            ctypes.memset(bits, 0, size * size * 4)
            if not DrawIconEx(dc, 0, 0, handle, size, size, 0, None, DI_NORMAL):
                return None
            data = ctypes.string_at(bits, size * size * 4)
            # Legacy mask icons have no alpha. Render over white as well to
            # distinguish opaque black ink from a transparent black pixel.
            if not any(data[3::4]):
                ctypes.memset(bits, 255, size * size * 4)
                if not DrawIconEx(dc, 0, 0, handle, size, size, 0, None, DI_NORMAL):
                    return None
                white = ctypes.string_at(bits, size * size * 4)
                data = bytes(
                    value
                    for offset in range(0, len(data), 4)
                    for value in (
                        data[offset],
                        data[offset + 1],
                        data[offset + 2],
                        min(255, 255 - max(white[offset + channel] - data[offset + channel] for channel in range(3))),
                    )
                )
            return Pixels(size, data)
        finally:
            SelectObject(dc, previous)
    finally:
        if bitmap:
            DeleteObject(bitmap)
        DeleteDC(dc)


def icon_size(handle: int) -> int | None:
    """An icon handle holds one image: its width in pixels, or None when Windows can't say."""
    info = ICONINFO()
    if not handle or not GetIconInfo(handle, info):
        return None
    try:
        bitmap = BITMAP()
        source = info.hbmColor or info.hbmMask
        if not source or not GetObjectW(source, ctypes.sizeof(BITMAP), ctypes.byref(bitmap)):
            return None
        return bitmap.bmWidth if 1 <= bitmap.bmWidth <= 256 else None
    finally:
        # GetIconInfo hands the caller copies of both bitmaps.
        for owned in (info.hbmColor, info.hbmMask):
            if owned:
                DeleteObject(owned)


def native_pixels(handle: int) -> Pixels | None:
    """A copy at the icon's own size, so no stretching blurs or blocks its edges."""
    return pixels(handle, icon_size(handle) or 32)


def window_pixels(hwnd: int) -> Pixels | None:
    """The window's small icon at its own size, which Windows sizes for the screen's scale.

    Bounded icon requests cannot wait indefinitely for an unresponsive application.
    """
    for kind in (ICON_SMALL2, ICON_SMALL, ICON_BIG):
        result = ctypes.c_size_t()
        if SendMessageTimeoutW(hwnd, WM_GETICON, kind, 0, SMTO_ABORTIFHUNG, 30, ctypes.byref(result)) and result.value:
            return native_pixels(result.value)
    return native_pixels(GetClassLongPtrW(hwnd, GCLP_HICONSM) or GetClassLongPtrW(hwnd, GCLP_HICON))
