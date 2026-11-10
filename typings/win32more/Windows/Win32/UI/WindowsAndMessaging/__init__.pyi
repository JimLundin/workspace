import ctypes
from collections.abc import Callable
from typing import Final

from win32more._win32 import ByReference
from win32more.Windows.Win32.Foundation import RECT
from win32more.Windows.Win32.UI.Accessibility import HIGHCONTRASTW

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

SW_HIDE: Final[int]
SW_SHOWNOACTIVATE: Final[int]

def FindWindowExW(parent: int | None, after: int | None, class_name: str | None, title: str | None) -> int | None: ...
def GetPropW(hwnd: int, name: str) -> int | None: ...

DI_NORMAL: Final[int]
GCLP_HICON: Final[int]
GCLP_HICONSM: Final[int]
ASFW_ANY: Final[int]
HWND_BROADCAST: Final[int]
HWND_TOPMOST: Final[int]
ICON_BIG: Final[int]
ICON_SMALL: Final[int]
ICON_SMALL2: Final[int]
MF_CHECKED: Final[int]
MF_GRAYED: Final[int]
MF_SEPARATOR: Final[int]
MF_STRING: Final[int]
MONITORINFOF_PRIMARY: Final[int]
SMTO_ABORTIFHUNG: Final[int]
SPI_GETCLIENTAREAANIMATION: Final[int]
SPI_GETHIGHCONTRAST: Final[int]
SWP_NOACTIVATE: Final[int]
SWP_NOMOVE: Final[int]
SWP_NOSIZE: Final[int]
TPM_NONOTIFY: Final[int]
TPM_RETURNCMD: Final[int]
TPM_RIGHTBUTTON: Final[int]
WM_COPYDATA: Final[int]
WM_GETICON: Final[int]
WM_NULL: Final[int]
WM_USER: Final[int]

class ICONINFO(ctypes.Structure):
    hbmMask: int | None
    hbmColor: int | None
    def __init__(self, *, fIcon: bool = False, hbmMask: int | None = None, hbmColor: int | None = None) -> None: ...

class WNDPROC:
    def __init__(self, callback: Callable[[int, int, int, int], int], /) -> None: ...

class WNDCLASSW(ctypes.Structure):
    hInstance: int | None
    lpszClassName: str | None
    def __init__(self, *, lpfnWndProc: WNDPROC, hInstance: int | None, lpszClassName: str) -> None: ...

def SystemParametersInfoW(action: int, parameter: int, value: ByReference[ctypes.c_int] | ByReference[HIGHCONTRASTW], update: int) -> int: ...
def DrawIconEx(dc: int, x: int, y: int, icon: int, width: int, height: int, step: int, brush: None, flags: int) -> int: ...
def GetIconInfo(icon: int, info: ICONINFO) -> int: ...
def DestroyIcon(icon: int) -> int: ...
def GetClassLongPtrW(hwnd: int, index: int) -> int: ...
def SendMessageTimeoutW(hwnd: int, message: int, wparam: int, lparam: int, flags: int, timeout: int, result: ByReference[ctypes.c_size_t]) -> int: ...
def SendNotifyMessageW(hwnd: int, message: int, wparam: int, lparam: int) -> int: ...
def SetPropW(hwnd: int, name: str, value: int) -> int: ...
def AllowSetForegroundWindow(process_id: int) -> int: ...
def RegisterWindowMessageW(name: str) -> int: ...
def UnregisterClassW(class_name: str | None, instance: int | None) -> int: ...
def DefWindowProcW(hwnd: int, message: int, wparam: int, lparam: int) -> int: ...
def CreatePopupMenu() -> int | None: ...
def AppendMenuW(menu: int | None, flags: int, item: int, text: str | None) -> int: ...
def TrackPopupMenu(menu: int | None, flags: int, x: int, y: int, reserved: int, hwnd: int, rect: None) -> int: ...
def DestroyMenu(menu: int | None) -> int: ...
def SetProcessDPIAware() -> int: ...

# The consumed fields of a thread's focus and caret: handles are None when null.
OBJID_CARET: Final[int]

class GUITHREADINFO(ctypes.Structure):
    cbSize: int
    hwndFocus: int | None
    hwndCaret: int | None
    rcCaret: RECT

def GetGUIThreadInfo(thread: int, info: ByReference[GUITHREADINFO]) -> int: ...
