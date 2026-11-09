# Consumed notification-area registration. Structures pass by reference; BOOL results are ints and HRESULT is signed.
import ctypes

from win32more._win32 import Guid
from win32more.Windows.Win32.Foundation import RECT

NIF_ICON: int
NIF_INFO: int
NIF_MESSAGE: int
NIF_TIP: int
NIM_ADD: int
NIM_DELETE: int
NIM_MODIFY: int

class NOTIFYICONDATAW(ctypes.Structure):
    cbSize: int
    hWnd: int | None
    uID: int
    uFlags: int
    uCallbackMessage: int
    hIcon: int | None
    szTip: str
    szInfo: str
    szInfoTitle: str
    dwInfoFlags: int
    guidItem: Guid

class NOTIFYICONIDENTIFIER(ctypes.Structure):
    def __init__(self, *, cbSize: int, hWnd: int | None, uID: int, guidItem: Guid) -> None: ...

def Shell_NotifyIconW(message: int, data: NOTIFYICONDATAW) -> int: ...
def Shell_NotifyIconGetRect(identifier: NOTIFYICONIDENTIFIER, location: RECT) -> int: ...
