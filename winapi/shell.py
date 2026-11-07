"""A window of our own with a window procedure, its notification-area (tray) icon,
popup menus, and icons drawn from pixels."""

import ctypes
from collections.abc import Callable, Sequence
from ctypes import wintypes
from dataclasses import dataclass, field
from typing import Final

from winapi._core import LRESULT, NativeFunction, fn, gdi32, kernel32, last_error, shell32, user32
from winapi.shapes import Rect

WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)


class WNDCLASSW(ctypes.Structure):
    style: int
    lpfnWndProc: NativeFunction[int]
    cbClsExtra: int
    cbWndExtra: int
    hInstance: int | None
    hIcon: int | None
    hCursor: int | None
    hbrBackground: int | None
    lpszMenuName: str | None
    lpszClassName: str | None
    _fields_ = (
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    )


class GUID(ctypes.Structure):
    Data1: int
    Data2: int
    Data3: int
    Data4: ctypes.Array[ctypes.c_ubyte]
    _fields_ = (("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD), ("Data4", wintypes.BYTE * 8))


class NOTIFYICONDATAW(ctypes.Structure):
    cbSize: int
    hWnd: int | None
    uID: int
    uFlags: int
    uCallbackMessage: int
    hIcon: int | None
    szTip: str
    dwState: int
    dwStateMask: int
    szInfo: str
    uVersion: int
    szInfoTitle: str
    dwInfoFlags: int
    guidItem: GUID
    hBalloonIcon: int | None
    _fields_ = (
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HICON),
        ("szTip", wintypes.WCHAR * 128),
        ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD),
        ("szInfo", wintypes.WCHAR * 256),
        ("uVersion", wintypes.UINT),
        ("szInfoTitle", wintypes.WCHAR * 64),
        ("dwInfoFlags", wintypes.DWORD),
        ("guidItem", GUID),
        ("hBalloonIcon", wintypes.HICON),
    )


class ICONINFO(ctypes.Structure):
    fIcon: int
    xHotspot: int
    yHotspot: int
    hbmMask: int | None
    hbmColor: int | None
    _fields_ = (
        ("fIcon", wintypes.BOOL),
        ("xHotspot", wintypes.DWORD),
        ("yHotspot", wintypes.DWORD),
        ("hbmMask", wintypes.HBITMAP),
        ("hbmColor", wintypes.HBITMAP),
    )


class NOTIFYICONIDENTIFIER(ctypes.Structure):
    cbSize: int
    hWnd: int | None
    uID: int
    guidItem: GUID
    _fields_ = (("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND), ("uID", wintypes.UINT), ("guidItem", GUID))


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


if ctypes.sizeof(NOTIFYICONDATAW) != (976 if ctypes.sizeof(ctypes.c_void_p) == 8 else 956):
    raise ImportError(f"NOTIFYICONDATAW is {ctypes.sizeof(NOTIFYICONDATAW)} bytes; Windows expects a different size")

_RegisterClassW = fn(user32, "RegisterClassW", wintypes.ATOM, ctypes.POINTER(WNDCLASSW))
_RegisterWindowMessage = fn(user32, "RegisterWindowMessageW", wintypes.UINT, wintypes.LPCWSTR)
TASKBAR_CREATED: Final = _RegisterWindowMessage("TaskbarCreated")
_UnregisterClassW = fn(user32, "UnregisterClassW", wintypes.BOOL, wintypes.LPCWSTR, wintypes.HINSTANCE)
_CreateWindowExW = fn(
    user32,
    "CreateWindowExW",
    wintypes.HWND,
    wintypes.DWORD,
    wintypes.LPCWSTR,
    wintypes.LPCWSTR,
    wintypes.DWORD,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.HWND,
    wintypes.HMENU,
    wintypes.HINSTANCE,
    wintypes.LPVOID,
)
_DefWindowProcW = fn(user32, "DefWindowProcW", LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
_DestroyWindow = fn(user32, "DestroyWindow", wintypes.BOOL, wintypes.HWND)
_GetModuleHandleW = fn(kernel32, "GetModuleHandleW", wintypes.HMODULE, wintypes.LPCWSTR)
_Shell_NotifyIconW = fn(shell32, "Shell_NotifyIconW", wintypes.BOOL, wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW))
_Shell_NotifyIconGetRect = fn(shell32, "Shell_NotifyIconGetRect", wintypes.LONG, ctypes.POINTER(NOTIFYICONIDENTIFIER), ctypes.POINTER(wintypes.RECT))
_CreatePopupMenu = fn(user32, "CreatePopupMenu", wintypes.HMENU)
_AppendMenuW = fn(user32, "AppendMenuW", wintypes.BOOL, wintypes.HMENU, wintypes.UINT, ctypes.c_size_t, wintypes.LPCWSTR)
_TrackPopupMenu = fn(
    user32, "TrackPopupMenu", wintypes.BOOL, wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND, ctypes.c_void_p
)
_DestroyMenu = fn(user32, "DestroyMenu", wintypes.BOOL, wintypes.HMENU)
_SetForegroundWindow = fn(user32, "SetForegroundWindow", wintypes.BOOL, wintypes.HWND)
_PostMessageW = fn(user32, "PostMessageW", wintypes.BOOL, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
_GetCursorPos = fn(user32, "GetCursorPos", wintypes.BOOL, ctypes.POINTER(wintypes.POINT))
_CreateIconIndirect = fn(user32, "CreateIconIndirect", wintypes.HICON, ctypes.POINTER(ICONINFO))
_DestroyIcon = fn(user32, "DestroyIcon", wintypes.BOOL, wintypes.HICON)
_CreateBitmap = fn(gdi32, "CreateBitmap", wintypes.HBITMAP, ctypes.c_int, ctypes.c_int, wintypes.UINT, wintypes.UINT, ctypes.c_void_p)
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
_DeleteObject = fn(gdi32, "DeleteObject", wintypes.BOOL, wintypes.HGDIOBJ)

_NIM_ADD, _NIM_MODIFY, _NIM_DELETE = 0, 1, 2
_NIF_MESSAGE, _NIF_ICON, _NIF_TIP, _NIF_INFO = 0x01, 0x02, 0x04, 0x10
NIIF_INFO, NIIF_WARNING = 0x01, 0x02
_MF_STRING, _MF_GRAYED, _MF_CHECKED, _MF_SEPARATOR = 0x0000, 0x0001, 0x0008, 0x0800
_TPM_RIGHTBUTTON, _TPM_NONOTIFY, _TPM_RETURNCMD = 0x0002, 0x0080, 0x0100
_WM_NULL: Final = 0

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
            return int(_DefWindowProcW(hwnd, message, wparam, lparam)) if result is None else result

        callback = WNDPROC(call)
        instance = _GetModuleHandleW(None)
        window_class = WNDCLASSW(0, callback, 0, 0, instance, None, None, None, None, class_name or f"{title} class")
        if not _RegisterClassW(ctypes.byref(window_class)):
            raise last_error()
        hwnd: int | None = _CreateWindowExW(0, window_class.lpszClassName, title, 0, 0, 0, 0, 0, None, None, instance, None)
        if not hwnd:
            raise last_error()
        return cls(int(hwnd), callback, window_class)

    def destroy(self) -> None:
        _DestroyWindow(self.handle)
        _UnregisterClassW(self._class.lpszClassName, self._class.hInstance)


@dataclass(frozen=True, slots=True)
class Icon:
    """An icon drawn from 32-bit BGRA pixels (with alpha), top row first."""

    handle: int

    @classmethod
    def draw(cls, size: int, bgra: bytes) -> Icon:
        header = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), size, -size, 1, 32, 0, 0, 0, 0, 0, 0)
        bits = ctypes.c_void_p()
        color = _CreateDIBSection(None, ctypes.byref(header), 0, ctypes.byref(bits), None, 0)
        ctypes.memmove(bits, bgra, size * size * 4)
        mask = _CreateBitmap(size, size, 1, 1, ctypes.create_string_buffer(size * size // 8))
        info = ICONINFO(True, 0, 0, mask, color)
        handle: int | None = _CreateIconIndirect(ctypes.byref(info))
        _DeleteObject(mask)
        _DeleteObject(color)
        if not handle:
            raise last_error()
        return cls(int(handle))

    def destroy(self) -> None:
        _DestroyIcon(self.handle)


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
        data.uFlags = _NIF_MESSAGE | _NIF_ICON | _NIF_TIP
        data.uCallbackMessage = message
        data.hIcon = icon.handle
        data.szTip = tip[:127]
        _Shell_NotifyIconW(_NIM_ADD, ctypes.byref(data))
        return cls(data)

    def update(self, icon: Icon, tip: str) -> None:
        self._data.uFlags = _NIF_ICON | _NIF_TIP
        self._data.hIcon = icon.handle
        self._data.szTip = tip[:127]
        _Shell_NotifyIconW(_NIM_MODIFY, ctypes.byref(self._data))

    def notify(self, title: str, text: str, kind: int = NIIF_INFO) -> None:
        """A notification ("balloon") next to the icon."""
        self._data.uFlags = _NIF_INFO
        self._data.szInfoTitle = title[:63]
        self._data.szInfo = text[:255]
        self._data.dwInfoFlags = kind
        _Shell_NotifyIconW(_NIM_MODIFY, ctypes.byref(self._data))

    def remove(self) -> None:
        _Shell_NotifyIconW(_NIM_DELETE, ctypes.byref(self._data))

    def restore(self) -> None:
        """Re-register the retained icon after Explorer or the tray host restarts."""
        self._data.uFlags = _NIF_MESSAGE | _NIF_ICON | _NIF_TIP
        _Shell_NotifyIconW(_NIM_ADD, ctypes.byref(self._data))

    def bounds(self) -> Rect | None:
        """Observe the host's icon position for native popup anchoring."""
        identifier = NOTIFYICONIDENTIFIER(ctypes.sizeof(NOTIFYICONIDENTIFIER), self._data.hWnd, self._data.uID, self._data.guidItem)
        rect = wintypes.RECT()
        if _Shell_NotifyIconGetRect(ctypes.byref(identifier), ctypes.byref(rect)) < 0:
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
    menu = _CreatePopupMenu()
    try:
        for item in items:
            if item.id == 0:
                _AppendMenuW(menu, _MF_SEPARATOR, 0, None)
            else:
                flags = _MF_STRING | (0 if item.enabled else _MF_GRAYED) | (_MF_CHECKED if item.checked else 0)
                _AppendMenuW(menu, flags, item.id, item.text)
        point = wintypes.POINT()
        _GetCursorPos(ctypes.byref(point))
        _SetForegroundWindow(window)  # without this the menu doesn't close when clicking elsewhere
        chosen = int(_TrackPopupMenu(menu, _TPM_RIGHTBUTTON | _TPM_NONOTIFY | _TPM_RETURNCMD, point.x, point.y, 0, window, None))
        _PostMessageW(window, _WM_NULL, 0, 0)
        return chosen
    finally:
        _DestroyMenu(menu)
