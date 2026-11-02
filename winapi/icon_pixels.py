"""Copy borrowed Windows icons into immutable pixels before their owners release them."""

import ctypes
from ctypes import wintypes
from dataclasses import dataclass

from winapi._core import ULONG_PTR, fn, gdi32, user32
from winapi.shell import BITMAPINFOHEADER

_CreateDIBSection = fn(
    gdi32,
    "CreateDIBSection",
    wintypes.HBITMAP,
    wintypes.HDC,
    ctypes.POINTER(BITMAPINFOHEADER),
    wintypes.UINT,
    ctypes.POINTER(ctypes.c_void_p),
    wintypes.HANDLE,
    wintypes.DWORD,
)
_CreateCompatibleDC = fn(gdi32, "CreateCompatibleDC", wintypes.HDC, wintypes.HDC)
_SelectObject = fn(gdi32, "SelectObject", wintypes.HGDIOBJ, wintypes.HDC, wintypes.HGDIOBJ)
_DeleteObject = fn(gdi32, "DeleteObject", wintypes.BOOL, wintypes.HGDIOBJ)
_DeleteDC = fn(gdi32, "DeleteDC", wintypes.BOOL, wintypes.HDC)
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
_SendMessageTimeout = fn(
    user32,
    "SendMessageTimeoutW",
    wintypes.LPARAM,
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
    wintypes.UINT,
    wintypes.UINT,
    ctypes.POINTER(ULONG_PTR),
)
_GetClassLongPtr = fn(user32, "GetClassLongPtrW", ULONG_PTR, wintypes.HWND, ctypes.c_int)


@dataclass(frozen=True, slots=True)
class Pixels:
    size: int
    bgra: bytes


def pixels(handle: int, size: int = 32) -> Pixels | None:
    """The adapter owns and releases its temporary DC/bitmap; the HICON is borrowed."""
    if not handle:
        return None
    dc = _CreateCompatibleDC(None)
    if not dc:
        return None
    bits = ctypes.c_void_p()
    header = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), size, -size, 1, 32, 0, 0, 0, 0, 0, 0)
    bitmap = _CreateDIBSection(dc, ctypes.byref(header), 0, ctypes.byref(bits), None, 0)
    try:
        if not bitmap:
            return None
        previous = _SelectObject(dc, bitmap)
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
            _SelectObject(dc, previous)
    finally:
        if bitmap:
            _DeleteObject(bitmap)
        _DeleteDC(dc)


def window_pixels(hwnd: int) -> Pixels | None:
    """Bounded icon requests cannot wait indefinitely for an unresponsive application."""
    for kind in (2, 0, 1):
        result = ULONG_PTR()
        if _SendMessageTimeout(hwnd, 0x007F, kind, 0, 2, 30, ctypes.byref(result)) and result.value:
            return pixels(result.value)
    return pixels(_GetClassLongPtr(hwnd, -34) or _GetClassLongPtr(hwnd, -14))
