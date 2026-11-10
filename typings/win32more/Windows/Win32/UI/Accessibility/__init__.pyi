import ctypes

from win32more._win32 import ByReference, ComPtr, Guid
from win32more.Windows.Win32.Foundation import RECT
from win32more.Windows.Win32.System.Variant import VARIANT

HCF_HIGHCONTRASTON: int

class HIGHCONTRASTW(ctypes.Structure):
    cbSize: int
    dwFlags: int
    def __init__(self, *, cbSize: int) -> None: ...

# The consumed caret and focus queries. Each call reports a signed HRESULT;
# MSAA's S_FALSE (1) means the app has nothing to report.

CUIAutomation: Guid

class IAccessible(ComPtr):
    def accLocation(
        self,
        left: ByReference[ctypes.c_int32],
        top: ByReference[ctypes.c_int32],
        width: ByReference[ctypes.c_int32],
        height: ByReference[ctypes.c_int32],
        child: VARIANT,
    ) -> int: ...

class IUIAutomationElement(ComPtr):
    def get_CurrentBoundingRectangle(self, bounds: ByReference[RECT]) -> int: ...

class IUIAutomation(ComPtr):
    def GetFocusedElement(self, element: IUIAutomationElement) -> int: ...

def AccessibleObjectFromWindow(hwnd: int, object_id: int, interface_id: Guid, result: ComPtr) -> int: ...
