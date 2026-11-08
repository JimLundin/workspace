"""Window placement and screenshot coordinates: plain arithmetic on rectangles."""

from typing import Literal

from winapi.shapes import Rect


def half(work: Rect, side: Literal["left", "right"], outer: Rect, visible: Rect) -> Rect:
    """Where to put a window (its outer rectangle) so what's drawn of it fills one
    half of the work area. Windows positions windows by their outer rectangle, which
    has invisible borders around what's drawn; they're added back on."""
    middle = work.left + work.width // 2
    target = Rect(work.left, work.top, middle, work.bottom) if side == "left" else Rect(middle, work.top, work.right, work.bottom)
    return framed(target, outer, visible)


def framed(target: Rect, outer: Rect, visible: Rect) -> Rect:
    """The outer rectangle that draws a window exactly over `target`, given where its
    outer and drawn rectangles are now: the invisible borders between them are added back on."""
    return Rect(
        target.left - (visible.left - outer.left),
        target.top - (visible.top - outer.top),
        target.right + (outer.right - visible.right),
        target.bottom + (outer.bottom - visible.bottom),
    )
