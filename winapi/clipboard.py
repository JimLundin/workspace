"""The clipboard, as text."""

import ctypes
import time

lazy from win32more.Windows.Win32.Foundation import GlobalFree
lazy from win32more.Windows.Win32.System.DataExchange import CloseClipboard, EmptyClipboard, OpenClipboard, SetClipboardData
lazy from win32more.Windows.Win32.System.Memory import GMEM_MOVEABLE, GlobalAlloc, GlobalLock, GlobalUnlock
lazy from win32more.Windows.Win32.System.Ole import CF_UNICODETEXT


def _open(hwnd: int) -> bool:
    # Another program may have it open for a moment; try for up to half a second.
    for _ in range(25):
        if OpenClipboard(hwnd):
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
        handle = GlobalAlloc(GMEM_MOVEABLE, size)
        if not handle:
            return False
        pointer = GlobalLock(handle)
        if not pointer:
            GlobalFree(handle)
            return False
        if not EmptyClipboard():
            GlobalUnlock(handle)
            GlobalFree(handle)
            return False
        ctypes.memmove(pointer, data, size)
        GlobalUnlock(handle)
        if not SetClipboardData(CF_UNICODETEXT, handle):
            GlobalFree(handle)
            return False
        return True  # the clipboard owns the memory now
    finally:
        CloseClipboard()
