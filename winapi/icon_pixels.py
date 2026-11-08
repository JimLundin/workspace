"""Copy borrowed Windows icons into immutable pixels before their owners release them."""

import ctypes
from ctypes import wintypes
from dataclasses import dataclass

from winapi._core import (
    ULONG_PTR,
    CreateCompatibleDC,
    CreateDIBSection,
    DeleteDC,
    DeleteObject,
    SelectObject,
    SendMessageTimeoutW,
    fn,
    gdi32,
    top_down,
    user32,
)
from winapi.shell import ICONINFO

_DrawIconEx = fn(
    user32,
    "DrawIconEx",
    wintypes.BOOL,
    wintypes.HDC,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.HICON,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.UINT,
    wintypes.HBRUSH,
    wintypes.UINT,
)
_GetClassLongPtr = fn(user32, "GetClassLongPtrW", ULONG_PTR, wintypes.HWND, ctypes.c_int)
_GetIconInfo = fn(user32, "GetIconInfo", wintypes.BOOL, wintypes.HICON, ctypes.POINTER(ICONINFO))
_GetObject = fn(gdi32, "GetObjectW", ctypes.c_int, wintypes.HGDIOBJ, ctypes.c_int, ctypes.c_void_p)


class BITMAP(ctypes.Structure):
    bmWidth: int  # The one field read; the rest give Windows its layout.
    _fields_ = (
        ("bmType", wintypes.LONG),
        ("bmWidth", wintypes.LONG),
        ("bmHeight", wintypes.LONG),
        ("bmWidthBytes", wintypes.LONG),
        ("bmPlanes", wintypes.WORD),
        ("bmBitsPixel", wintypes.WORD),
        ("bmBits", ctypes.c_void_p),
    )


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
    bitmap = CreateDIBSection(dc, ctypes.byref(header), 0, ctypes.byref(bits), None, 0)
    try:
        if not bitmap:
            return None
        previous = SelectObject(dc, bitmap)
        try:
            ctypes.memset(bits, 0, size * size * 4)
            if not _DrawIconEx(dc, 0, 0, handle, size, size, 0, None, 3):
                return None
            data = ctypes.string_at(bits, size * size * 4)
            # Legacy mask icons have no alpha. Render over white as well to
            # distinguish opaque black ink from a transparent black pixel.
            if not any(data[3::4]):
                ctypes.memset(bits, 255, size * size * 4)
                if not _DrawIconEx(dc, 0, 0, handle, size, size, 0, None, 3):
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
    if not handle or not _GetIconInfo(handle, ctypes.byref(info)):
        return None
    try:
        bitmap = BITMAP()
        source = info.hbmColor or info.hbmMask
        if not source or not _GetObject(source, ctypes.sizeof(BITMAP), ctypes.byref(bitmap)):
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
    for kind in (2, 0, 1):
        result = ULONG_PTR()
        if SendMessageTimeoutW(hwnd, 0x007F, kind, 0, 2, 30, ctypes.byref(result)) and result.value:
            return native_pixels(result.value)
    return native_pixels(_GetClassLongPtr(hwnd, -34) or _GetClassLongPtr(hwnd, -14))
