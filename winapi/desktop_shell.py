"""Taskbar visibility and the independent recovery companion's process wait."""

import ctypes
from collections.abc import Callable
from ctypes import wintypes

from winapi._core import fn, kernel32, user32

_FindWindowEx = fn(user32, "FindWindowExW", wintypes.HWND, wintypes.HWND, wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR)
_IsWindowVisible = fn(user32, "IsWindowVisible", wintypes.BOOL, wintypes.HWND)
_ShowWindow = fn(user32, "ShowWindow", wintypes.BOOL, wintypes.HWND, ctypes.c_int)
_OpenProcess = fn(kernel32, "OpenProcess", wintypes.HANDLE, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
_WaitForSingleObject = fn(kernel32, "WaitForSingleObject", wintypes.DWORD, wintypes.HANDLE, wintypes.DWORD)
_CloseHandle = fn(kernel32, "CloseHandle", wintypes.BOOL, wintypes.HANDLE)


def taskbars() -> tuple[int, ...]:
    handles: list[int] = []
    for name in ("Shell_TrayWnd", "Shell_SecondaryTrayWnd"):
        previous = 0
        while found := _FindWindowEx(0, previous, name, None):
            previous = int(found)
            handles.append(previous)
    return tuple(handles)


def visible(hwnd: int) -> bool:
    return bool(_IsWindowVisible(hwnd))


def taskbar_visible(hwnd: int, *, show: bool) -> None:
    if hwnd in taskbars():
        _ShowWindow(hwnd, 4 if show else 0)


def wait_for_exit(pid: int, ready: Callable[[], None] | None = None) -> None:
    """Used only by the taskbar recovery companion, never on a UI thread."""
    process = _OpenProcess(0x00100000, False, pid)
    if process:
        try:
            if ready is not None:
                ready()
            _WaitForSingleObject(process, 0xFFFFFFFF)
        finally:
            _CloseHandle(process)
