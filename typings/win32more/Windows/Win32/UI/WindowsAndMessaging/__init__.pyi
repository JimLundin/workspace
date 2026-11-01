from typing import Final

LWA_ALPHA: Final[int]
WS_EX_LAYERED: Final[int]
WS_EX_NOACTIVATE: Final[int]
WS_EX_NOREDIRECTIONBITMAP: Final[int]
WS_EX_TOOLWINDOW: Final[int]
WS_EX_TRANSPARENT: Final[int]
WS_POPUP: Final[int]

def CreateWindowExW(
    extended_style: int,
    class_name: str,
    title: str,
    style: int,
    x: int,
    y: int,
    width: int,
    height: int,
    parent: int | None,
    menu: int | None,
    instance: int | None,
    parameter: None,
) -> int | None: ...
def SetWindowPos(hwnd: int, after: int, x: int, y: int, width: int, height: int, flags: int) -> int: ...
def GetWindow(hwnd: int, command: int) -> int | None: ...
def GetWindowThreadProcessId(hwnd: int, process_id: None) -> int: ...

# SDK HWND/COLORREF/BYTE/flags signature; the native BOOL result is an int.
def SetLayeredWindowAttributes(hwnd: int, color_key: int, alpha: int, flags: int) -> int: ...
