"""Taskbar visibility and the independent recovery companion's process wait."""

from collections.abc import Callable, Iterator
from ctypes import wintypes

from winapi._core import CloseHandle, IsWindowVisible, OpenProcess, ShowWindow, WaitForSingleObject, fn, user32

_FindWindowEx = fn(user32, "FindWindowExW", wintypes.HWND, wintypes.HWND, wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR)
_GetProp = fn(user32, "GetPropW", wintypes.HANDLE, wintypes.HWND, wintypes.LPCWSTR)


def _windows(name: str) -> Iterator[int]:
    """Each top-level window of class `name`, in Z order."""
    previous = 0
    while found := _FindWindowEx(0, previous, name, None):
        previous = int(found)
        yield previous


def taskbars() -> tuple[int, ...]:
    return tuple(
        handle for name in ("Shell_TrayWnd", "Shell_SecondaryTrayWnd") for handle in _windows(name) if not _GetProp(handle, "workspace tray proxy")
    )


def visible(hwnd: int) -> bool:
    return bool(IsWindowVisible(hwnd))


def taskbar_visible(hwnd: int, *, show: bool) -> None:
    if hwnd in taskbars():
        ShowWindow(hwnd, 4 if show else 0)


def wait_for_exit(pid: int, ready: Callable[[], None] | None = None) -> None:
    """Used only by the taskbar recovery companion, never on a UI thread."""
    process = OpenProcess(0x00100000, False, pid)
    if process:
        try:
            if ready is not None:
                ready()
            WaitForSingleObject(process, 0xFFFFFFFF)
        finally:
            CloseHandle(process)
