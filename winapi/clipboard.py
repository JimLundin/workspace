"""The clipboard, as text."""

import ctypes
import time
from ctypes import wintypes
from typing import Final

from winapi._core import fn, kernel32, user32

_OpenClipboard = fn(user32, "OpenClipboard", wintypes.BOOL, wintypes.HWND)
_CloseClipboard = fn(user32, "CloseClipboard", wintypes.BOOL)
_EmptyClipboard = fn(user32, "EmptyClipboard", wintypes.BOOL)
_SetClipboardData = fn(user32, "SetClipboardData", wintypes.HANDLE, wintypes.UINT, wintypes.HANDLE)
_GlobalAlloc = fn(kernel32, "GlobalAlloc", wintypes.HGLOBAL, wintypes.UINT, ctypes.c_size_t)
_GlobalLock = fn(kernel32, "GlobalLock", wintypes.LPVOID, wintypes.HGLOBAL)
_GlobalUnlock = fn(kernel32, "GlobalUnlock", wintypes.BOOL, wintypes.HGLOBAL)
_GlobalFree = fn(kernel32, "GlobalFree", wintypes.HGLOBAL, wintypes.HGLOBAL)

_CF_UNICODETEXT: Final = 13
_GMEM_MOVEABLE: Final = 0x0002


def _open(hwnd: int) -> bool:
    # Another program may have it open for a moment; try for up to half a second.
    for _ in range(25):
        if _OpenClipboard(hwnd):
            return True
        time.sleep(0.02)
    return False


def set_text(hwnd: int, text: str) -> bool:
    """Replaces the clipboard's contents with text. `hwnd` becomes its owner."""
    data = ctypes.create_unicode_buffer(text)
    size = ctypes.sizeof(data)
    if not _open(hwnd):
        return False
    try:
        handle = _GlobalAlloc(_GMEM_MOVEABLE, size)
        if not handle:
            return False
        pointer = _GlobalLock(handle)
        if not pointer:
            _GlobalFree(handle)
            return False
        if not _EmptyClipboard():
            _GlobalUnlock(handle)
            _GlobalFree(handle)
            return False
        ctypes.memmove(pointer, data, size)
        _GlobalUnlock(handle)
        if not _SetClipboardData(_CF_UNICODETEXT, handle):
            _GlobalFree(handle)
            return False
        return True  # the clipboard owns the memory now
    finally:
        _CloseClipboard()
