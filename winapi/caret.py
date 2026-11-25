import ctypes
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass

lazy from win32more import FAILED
lazy from win32more._win32 import Guid
lazy from win32more.Windows.Win32.Foundation import POINT, RECT
lazy from win32more.Windows.Win32.Graphics.Gdi import ClientToScreen
lazy from win32more.Windows.Win32.System.Com import (
    CLSCTX_INPROC_SERVER,
    COINIT_MULTITHREADED,
    SAFEARRAY,
    CoCreateInstance,
    CoInitializeEx,
    CoUninitialize,
)
lazy from win32more.Windows.Win32.System.Ole import (
    SafeArrayAccessData,
    SafeArrayDestroy,
    SafeArrayGetUBound,
    SafeArrayUnaccessData,
)
lazy from win32more.Windows.Win32.System.Variant import VARIANT, VT_I4
lazy from win32more.Windows.Win32.UI.Accessibility import (
    AccessibleObjectFromWindow,
    CUIAutomation,
    IAccessible,
    IUIAutomation,
    IUIAutomationElement,
    IUIAutomationTextPattern,
    IUIAutomationTextRange,
    IUIAutomationTextRangeArray,
    TextPatternRangeEndpoint_End,
    TextPatternRangeEndpoint_Start,
    TextUnit_Character,
    UIA_TextPatternId,
)
lazy from win32more.Windows.Win32.UI.WindowsAndMessaging import (
    GUITHREADINFO,
    OBJID_CARET,
    GetGUIThreadInfo,
    GetWindowThreadProcessId,
)

from winapi.shapes import Rect


@dataclass(frozen=True, slots=True)
class Caret:
    rect: Rect


@dataclass(frozen=True, slots=True)
class Field:
    rect: Rect


@dataclass(frozen=True, slots=True)
class Window:
    rect: Rect


type Anchor = Caret | Field | Window
"""Where typed text goes, from the most precise to the least."""


_IACCESSIBLE = "{618736e0-3c3d-11cf-810c-00aa00389b71}"
_IUIAUTOMATION = "{30cbe57d-d9d0-452a-ab13-7ac5ac4825ee}"
_ITEXTPATTERN = "{32eba289-3583-42c9-9c59-3b6d9a1e9b6a}"
_CHILDID_SELF = 0


def _shown(rect: Rect) -> Rect | None:
    return rect if rect.height > 0 and rect.width >= 0 else None


def _thread(window: int) -> GUITHREADINFO | None:
    info = GUITHREADINFO()
    info.cbSize = ctypes.sizeof(GUITHREADINFO)
    return (
        info
        if GetGUIThreadInfo(
            GetWindowThreadProcessId(window, None), ctypes.byref(info)
        )
        else None
    )


def thread_caret(window: int) -> Caret | None:
    if not (info := _thread(window)) or not info.hwndCaret:
        return None
    corners = (
        POINT(info.rcCaret.left, info.rcCaret.top),
        POINT(info.rcCaret.right, info.rcCaret.bottom),
    )
    if not all(
        ClientToScreen(info.hwndCaret, ctypes.byref(corner))
        for corner in corners
    ):
        return None
    top_left, bottom_right = corners
    shown = _shown(Rect(top_left.x, top_left.y, bottom_right.x, bottom_right.y))
    return Caret(shown) if shown is not None else None


@contextmanager
def com_thread() -> Generator[bool]:
    started = not FAILED(CoInitializeEx(None, COINIT_MULTITHREADED))
    try:
        yield started
    finally:
        if started:
            CoUninitialize()


def _accessible_caret(window: int) -> Caret | None:
    caret = IAccessible(own=True)
    if (
        FAILED(
            AccessibleObjectFromWindow(
                window, OBJID_CARET, Guid(_IACCESSIBLE), caret
            )
        )
        or not caret
    ):
        return None
    left, top, width, height = (
        ctypes.c_int32(),
        ctypes.c_int32(),
        ctypes.c_int32(),
        ctypes.c_int32(),
    )
    child = VARIANT()
    child.Anonymous.Anonymous.vt = VT_I4
    child.Anonymous.Anonymous.Anonymous.lVal = _CHILDID_SELF
    if (
        caret.accLocation(
            ctypes.byref(left),
            ctypes.byref(top),
            ctypes.byref(width),
            ctypes.byref(height),
            child,
        )
        != 0
    ):
        return None
    shown = _shown(
        Rect(
            left.value,
            top.value,
            left.value + width.value,
            top.value + height.value,
        )
    )
    return Caret(shown) if shown is not None else None


def _focused_element() -> IUIAutomationElement | None:
    automation = IUIAutomation(own=True)
    focused = IUIAutomationElement(own=True)
    if (
        FAILED(
            CoCreateInstance(
                CUIAutomation,
                None,
                CLSCTX_INPROC_SERVER,
                Guid(_IUIAUTOMATION),
                automation,
            )
        )
        or FAILED(automation.GetFocusedElement(focused))
        or not focused
    ):
        return None
    return focused


def _first_rect(range_: IUIAutomationTextRange) -> Rect | None:
    array = ctypes.POINTER(SAFEARRAY)()
    if FAILED(range_.GetBoundingRectangles(ctypes.byref(array))) or not array:
        return None
    try:
        upper, data = ctypes.c_int32(), ctypes.c_void_p()
        if (
            FAILED(SafeArrayGetUBound(array, 1, ctypes.byref(upper)))
            or upper.value < 3
            or FAILED(SafeArrayAccessData(array, ctypes.byref(data)))
        ):
            return None
        left, top, width, height = (
            round(value)
            for value in (ctypes.c_double * 4).from_address(data.value or 0)
        )
        SafeArrayUnaccessData(array)
    finally:
        SafeArrayDestroy(array)
    return _shown(Rect(left, top, left + width, top + height))


def _text_caret(focused: IUIAutomationElement) -> Caret | None:
    pattern = IUIAutomationTextPattern(own=True)
    selection = IUIAutomationTextRangeArray(own=True)
    count = ctypes.c_int32()
    cursor = IUIAutomationTextRange(own=True)
    if (
        FAILED(
            focused.GetCurrentPatternAs(
                UIA_TextPatternId, Guid(_ITEXTPATTERN), pattern
            )
        )
        or not pattern
        or FAILED(pattern.GetSelection(selection))
        or not selection
        or FAILED(selection.get_Length(ctypes.byref(count)))
        or count.value < 1
        or FAILED(selection.GetElement(count.value - 1, cursor))
        or not cursor
        or FAILED(
            cursor.MoveEndpointByRange(
                TextPatternRangeEndpoint_Start,
                cursor,
                TextPatternRangeEndpoint_End,
            )
        )
        or FAILED(cursor.ExpandToEnclosingUnit(TextUnit_Character))
    ):
        return None
    shown = _first_rect(cursor)
    return Caret(shown) if shown is not None else None


def _focused_field(focused: IUIAutomationElement) -> Field | None:
    bounds = RECT()
    if FAILED(focused.get_CurrentBoundingRectangle(ctypes.byref(bounds))):
        return None
    shown = _shown(Rect(bounds.left, bounds.top, bounds.right, bounds.bottom))
    return Field(shown) if shown is not None else None


def _focused_anchor() -> Caret | Field | None:
    if (focused := _focused_element()) is None:
        return None
    return _text_caret(focused) or _focused_field(focused)


def accessible_anchor(window: int) -> Caret | Field | None:
    focus = (
        info.hwndFocus
        if (info := _thread(window)) and info.hwndFocus
        else window
    )
    return _accessible_caret(focus) or _focused_anchor()
