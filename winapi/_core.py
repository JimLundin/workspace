"""The DLLs, and how a function prototype is declared. Internal to `winapi`."""

import ctypes
import uuid
from ctypes import wintypes
from typing import Protocol, overload

from winapi.shapes import Rect

ULONG_PTR = ctypes.c_size_t
LONG_PTR = ctypes.c_ssize_t
LRESULT = LONG_PTR

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
winmm = ctypes.WinDLL("winmm", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)
comctl32 = ctypes.WinDLL("comctl32", use_last_error=True)
dxva2 = ctypes.WinDLL("dxva2", use_last_error=True)
wtsapi32 = ctypes.WinDLL("wtsapi32", use_last_error=True)
powrprof = ctypes.WinDLL("powrprof", use_last_error=True)
ole32 = ctypes.WinDLL("ole32", use_last_error=True)


class Scalar[T](Protocol):
    """A ctypes scalar exposes the converted native return value."""

    value: T


class NativeFunction[T](Protocol):
    """ctypes validates positional ABI arguments; the prototype fixes the result."""

    def __call__(self, *args: object) -> T: ...


@overload
def fn[T](dll: ctypes.WinDLL, name: str, restype: type[Scalar[T]], *argtypes: type[object]) -> NativeFunction[T]: ...


@overload
def fn(dll: ctypes.WinDLL, name: str, restype: None, *argtypes: type[object]) -> NativeFunction[None]: ...


def fn[T](
    dll: ctypes.WinDLL,
    name: str,
    restype: type[Scalar[T]] | None,
    *argtypes: type[object],
) -> NativeFunction[T] | NativeFunction[None]:
    """A typed foreign function: `fn(user32, "GetForegroundWindow", HWND)`."""
    prototype = ctypes.WINFUNCTYPE(restype, *argtypes, use_last_error=True)
    return prototype((name, dll))


class GUID(ctypes.Structure):
    Data1: int
    Data2: int
    Data3: int
    Data4: ctypes.Array[ctypes.c_ubyte]
    _fields_ = (("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD), ("Data4", wintypes.BYTE * 8))


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


def top_down(width: int, height: int) -> BITMAPINFOHEADER:
    """A 32-bit device-independent bitmap's header, top row first."""
    return BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), width, -height, 1, 32, 0, 0, 0, 0, 0, 0)


# Functions more than one module calls, each declared once.
FindWindowW = fn(user32, "FindWindowW", wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR)
AllowSetForegroundWindow = fn(user32, "AllowSetForegroundWindow", wintypes.BOOL, wintypes.DWORD)
CloseHandle = fn(kernel32, "CloseHandle", wintypes.BOOL, wintypes.HANDLE)
CoCreateInstance = fn(ole32, "CoCreateInstance", ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p)
CreateCompatibleDC = fn(gdi32, "CreateCompatibleDC", wintypes.HDC, wintypes.HDC)
CreateEventW = fn(kernel32, "CreateEventW", wintypes.HANDLE, wintypes.LPVOID, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR)
CreateWindowExW = fn(
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
DeleteDC = fn(gdi32, "DeleteDC", wintypes.BOOL, wintypes.HDC)
DeleteObject = fn(gdi32, "DeleteObject", wintypes.BOOL, wintypes.HGDIOBJ)
DestroyWindow = fn(user32, "DestroyWindow", wintypes.BOOL, wintypes.HWND)
GetAsyncKeyState = fn(user32, "GetAsyncKeyState", ctypes.c_short, ctypes.c_int)
GetCurrentThreadId = fn(kernel32, "GetCurrentThreadId", wintypes.DWORD)
GetCursorPos = fn(user32, "GetCursorPos", wintypes.BOOL, ctypes.POINTER(wintypes.POINT))
GetDC = fn(user32, "GetDC", wintypes.HDC, wintypes.HWND)
GetForegroundWindow = fn(user32, "GetForegroundWindow", wintypes.HWND)
GetModuleHandleW = fn(kernel32, "GetModuleHandleW", wintypes.HMODULE, wintypes.LPCWSTR)
GetWindowThreadProcessId = fn(user32, "GetWindowThreadProcessId", wintypes.DWORD, wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
IsWindowVisible = fn(user32, "IsWindowVisible", wintypes.BOOL, wintypes.HWND)
OpenProcess = fn(kernel32, "OpenProcess", wintypes.HANDLE, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
PostMessageW = fn(user32, "PostMessageW", wintypes.BOOL, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
ReleaseDC = fn(user32, "ReleaseDC", ctypes.c_int, wintypes.HWND, wintypes.HDC)
SelectObject = fn(gdi32, "SelectObject", wintypes.HGDIOBJ, wintypes.HDC, wintypes.HGDIOBJ)
SendMessageTimeoutW = fn(
    user32,
    "SendMessageTimeoutW",
    LRESULT,
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
    wintypes.UINT,
    wintypes.UINT,
    ctypes.POINTER(ULONG_PTR),
)
SetForegroundWindow = fn(user32, "SetForegroundWindow", wintypes.BOOL, wintypes.HWND)
SetWindowPos = fn(
    user32, "SetWindowPos", wintypes.BOOL, wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT
)
ShowWindow = fn(user32, "ShowWindow", wintypes.BOOL, wintypes.HWND, ctypes.c_int)
WaitForSingleObject = fn(kernel32, "WaitForSingleObject", wintypes.DWORD, wintypes.HANDLE, wintypes.DWORD)

CreateDIBSection = fn(
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


def optional_fn[T](
    dll: ctypes.WinDLL,
    name: str,
    restype: type[Scalar[T]],
    *argtypes: type[object],
) -> NativeFunction[T] | None:
    """Like `fn`, for functions older Windows versions don't have; None if missing."""
    try:
        return fn(dll, name, restype, *argtypes)
    except AttributeError:
        return None


def rect(r: wintypes.RECT) -> Rect:
    return Rect(int(r.left), int(r.top), int(r.right), int(r.bottom))


def last_error() -> OSError:
    return ctypes.WinError(ctypes.get_last_error())


type GuidBuffer = ctypes.Array[ctypes.c_char]


def guid_buffer(value: str) -> GuidBuffer:
    """A COM class or interface identifier, as the 16 bytes COM reads."""
    return ctypes.create_string_buffer(uuid.UUID(value).bytes_le, 16)


def com_method(owner: str, pointer: ctypes.c_void_p, index: int, *arguments: type[object]) -> NativeFunction[int]:
    """The method at `index` in a COM object's table, returning its HRESULT: the object's first pointer is its table."""
    table = ctypes.c_void_p.from_address(pointer.value).value if pointer.value else None
    address = ctypes.c_void_p.from_address(table + index * ctypes.sizeof(ctypes.c_void_p)).value if table else None
    if address is None:
        raise OSError(f"{owner} has no method table.")
    return ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *arguments)(address)
