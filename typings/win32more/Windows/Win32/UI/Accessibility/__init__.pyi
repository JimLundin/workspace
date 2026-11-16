import ctypes

from win32more._win32 import ByReference, ComPtr, Guid
from win32more.Windows.Win32.Foundation import RECT
from win32more.Windows.Win32.System.Com import SAFEARRAY
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

UIA_TextPatternId: int
TextUnit_Character: int
TextPatternRangeEndpoint_Start: int
TextPatternRangeEndpoint_End: int

class IUIAutomationTextRange(ComPtr):
    def MoveEndpointByRange(
        self, endpoint: int, range: IUIAutomationTextRange, target: int
    ) -> int: ...
    def ExpandToEnclosingUnit(self, unit: int) -> int: ...
    def GetBoundingRectangles(
        self, rectangles: ByReference[ctypes._Pointer[SAFEARRAY]]
    ) -> int: ...

class IUIAutomationTextRangeArray(ComPtr):
    def get_Length(self, length: ByReference[ctypes.c_int32]) -> int: ...
    def GetElement(
        self, index: int, element: IUIAutomationTextRange
    ) -> int: ...

class IUIAutomationTextPattern(ComPtr):
    def GetSelection(self, ranges: IUIAutomationTextRangeArray) -> int: ...

class IUIAutomationElement(ComPtr):
    def get_CurrentBoundingRectangle(
        self, bounds: ByReference[RECT]
    ) -> int: ...
    def GetCurrentPatternAs(
        self, pattern: int, interface_id: Guid, result: ComPtr
    ) -> int: ...

class IUIAutomation(ComPtr):
    def GetFocusedElement(self, element: IUIAutomationElement) -> int: ...

def AccessibleObjectFromWindow(
    hwnd: int, object_id: int, interface_id: Guid, result: ComPtr
) -> int: ...
