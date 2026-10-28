"""The DLLs, and how a function prototype is declared. Internal to `winapi`."""

import ctypes
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
    dll: ctypes.WinDLL, name: str, restype: type[Scalar[T]] | None, *argtypes: type[object],
) -> NativeFunction[T] | NativeFunction[None]:
    """A typed foreign function: `fn(user32, "GetForegroundWindow", HWND)`."""
    prototype = ctypes.WINFUNCTYPE(restype, *argtypes, use_last_error=True)
    return prototype((name, dll))


def optional_fn[T](
    dll: ctypes.WinDLL, name: str, restype: type[Scalar[T]], *argtypes: type[object],
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
