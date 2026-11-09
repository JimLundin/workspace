"""A window of our own with a window procedure, its notification-area (tray) icon,
popup menus, and icons drawn from pixels."""

import ctypes
from collections.abc import Callable, Sequence
from ctypes import wintypes
from dataclasses import dataclass, field
from typing import Final

lazy from win32more.Windows.Win32.Foundation import RECT
lazy from win32more.Windows.Win32.Graphics.Gdi import DIB_RGB_COLORS, CreateBitmap, CreateDIBSection
lazy from win32more.Windows.Win32.UI.Shell import (
    NIF_ICON,
    NIF_INFO,
    NIF_MESSAGE,
    NIF_TIP,
    NIM_ADD,
    NIM_DELETE,
    NIM_MODIFY,
    NOTIFYICONDATAW,
    NOTIFYICONIDENTIFIER,
    Shell_NotifyIconGetRect,
    Shell_NotifyIconW,
)
lazy from win32more.Windows.Win32.UI.WindowsAndMessaging import (
    ICONINFO,
    MF_CHECKED,
    MF_GRAYED,
    MF_SEPARATOR,
    MF_STRING,
    TPM_NONOTIFY,
    TPM_RETURNCMD,
    TPM_RIGHTBUTTON,
    WM_NULL,
    WNDCLASSW,
    WNDPROC,
    AppendMenuW,
    CreatePopupMenu,
    DefWindowProcW,
    DestroyIcon,
    DestroyMenu,
    RegisterWindowMessageW,
    TrackPopupMenu,
    UnregisterClassW,
)

from winapi._core import (
    CreateWindowExW,
    DeleteObject,
    DestroyWindow,
    GetCursorPos,
    GetModuleHandleW,
    PostMessageW,
    SetForegroundWindow,
    fn,
    last_error,
    user32,
)
from winapi.screen import top_down
from winapi.shapes import Rect

# Failures read the thread's last error, which win32more's bindings don't keep.
_RegisterClassW = fn(user32, "RegisterClassW", wintypes.ATOM, ctypes.c_void_p)
_CreateIconIndirect = fn(user32, "CreateIconIndirect", wintypes.HICON, ctypes.c_void_p)

TASKBAR_CREATED: Final = RegisterWindowMessageW("TaskbarCreated")
NIIF_INFO, NIIF_WARNING = 0x01, 0x02

WindowProc = Callable[[int, int, int, int], "int | None"]
"""(hwnd, message, wparam, lparam) -> result, or None for Windows' default handling."""


@dataclass(frozen=True, slots=True)
class AppWindow:
    """A hidden top-level window with our own window procedure. Other processes can
    find it by its title. Its messages are handled while this thread runs a message
    loop (`system.run_message_loop`)."""

    handle: int
    _callback: object
    """The ctypes callback, kept alive as long as the window."""
    _class: WNDCLASSW

    @classmethod
    def create(cls, title: str, proc: WindowProc, *, class_name: str | None = None) -> AppWindow:
        def call(hwnd: int, message: int, wparam: int, lparam: int) -> int:
            result = proc(int(hwnd or 0), int(message), int(wparam or 0), int(lparam or 0))
            return DefWindowProcW(hwnd, message, wparam, lparam) if result is None else result

        callback = WNDPROC(call)
        instance = GetModuleHandleW(None)
        window_class = WNDCLASSW(lpfnWndProc=callback, hInstance=instance, lpszClassName=class_name or f"{title} class")
        if not _RegisterClassW(ctypes.byref(window_class)):
            raise last_error()
        hwnd: int | None = CreateWindowExW(0, window_class.lpszClassName, title, 0, 0, 0, 0, 0, None, None, instance, None)
        if not hwnd:
            raise last_error()
        return cls(int(hwnd), callback, window_class)

    def destroy(self) -> None:
        DestroyWindow(self.handle)
        UnregisterClassW(self._class.lpszClassName, self._class.hInstance)


@dataclass(frozen=True, slots=True)
class Icon:
    """An icon drawn from 32-bit BGRA pixels (with alpha), top row first."""

    handle: int

    @classmethod
    def draw(cls, size: int, bgra: bytes) -> Icon:
        header = top_down(size, size)
        bits = ctypes.c_void_p()
        color = CreateDIBSection(None, header, DIB_RGB_COLORS, ctypes.byref(bits), None, 0)
        ctypes.memmove(bits, bgra, size * size * 4)
        mask = CreateBitmap(size, size, 1, 1, ctypes.create_string_buffer(size * size // 8))
        info = ICONINFO(fIcon=True, hbmMask=mask, hbmColor=color)
        handle: int | None = _CreateIconIndirect(ctypes.byref(info))
        DeleteObject(mask)
        DeleteObject(color)
        if not handle:
            raise last_error()
        return cls(int(handle))

    def destroy(self) -> None:
        DestroyIcon(self.handle)


@dataclass(frozen=True, slots=True)
class TrayIcon:
    """An icon in the notification area. Mouse events on it arrive at `window` as
    `message`, with the mouse message (WM_RBUTTONUP...) in lparam."""

    _data: NOTIFYICONDATAW
    """The shell's registration, which each update rewrites in place for `Shell_NotifyIconW`."""

    @classmethod
    def add(cls, window: int, message: int, icon: Icon, tip: str) -> TrayIcon:
        data = NOTIFYICONDATAW()
        data.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        data.hWnd = window
        data.uID = 1
        data.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        data.uCallbackMessage = message
        data.hIcon = icon.handle
        data.szTip = tip[:127]
        Shell_NotifyIconW(NIM_ADD, data)
        return cls(data)

    def update(self, icon: Icon, tip: str) -> None:
        self._data.uFlags = NIF_ICON | NIF_TIP
        self._data.hIcon = icon.handle
        self._data.szTip = tip[:127]
        Shell_NotifyIconW(NIM_MODIFY, self._data)

    def notify(self, title: str, text: str, kind: int = NIIF_INFO) -> None:
        """A notification ("balloon") next to the icon."""
        self._data.uFlags = NIF_INFO
        self._data.szInfoTitle = title[:63]
        self._data.szInfo = text[:255]
        self._data.dwInfoFlags = kind
        Shell_NotifyIconW(NIM_MODIFY, self._data)

    def remove(self) -> None:
        Shell_NotifyIconW(NIM_DELETE, self._data)

    def restore(self) -> None:
        """Re-register the retained icon after Explorer or the tray host restarts."""
        self._data.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        Shell_NotifyIconW(NIM_ADD, self._data)

    def bounds(self) -> Rect | None:
        """Observe the host's icon position for native popup anchoring."""
        identifier = NOTIFYICONIDENTIFIER(
            cbSize=ctypes.sizeof(NOTIFYICONIDENTIFIER), hWnd=self._data.hWnd, uID=self._data.uID, guidItem=self._data.guidItem
        )
        rect = RECT()
        if Shell_NotifyIconGetRect(identifier, rect) < 0:
            return None
        return Rect(rect.left, rect.top, rect.right, rect.bottom)


@dataclass(frozen=True, slots=True)
class MenuItem:
    id: int
    """What `show_menu` returns when this is chosen; 0 for a separator."""
    text: str = ""
    enabled: bool = field(default=True, kw_only=True)
    checked: bool = field(default=False, kw_only=True)


def show_menu(window: int, items: Sequence[MenuItem]) -> int:
    """A popup menu at the mouse; the chosen item's id, or 0 if dismissed."""
    menu = CreatePopupMenu()
    try:
        for item in items:
            if item.id == 0:
                AppendMenuW(menu, MF_SEPARATOR, 0, None)
            else:
                flags = MF_STRING | (0 if item.enabled else MF_GRAYED) | (MF_CHECKED if item.checked else 0)
                AppendMenuW(menu, flags, item.id, item.text)
        point = wintypes.POINT()
        GetCursorPos(ctypes.byref(point))
        SetForegroundWindow(window)  # without this the menu doesn't close when clicking elsewhere
        chosen = int(TrackPopupMenu(menu, TPM_RIGHTBUTTON | TPM_NONOTIFY | TPM_RETURNCMD, point.x, point.y, 0, window, None))
        PostMessageW(window, WM_NULL, 0, 0)
        return chosen
    finally:
        DestroyMenu(menu)
