from typing import Literal

from winapi.shapes import Rect


def half(
    work: Rect, side: Literal["left", "right"], outer: Rect, visible: Rect
) -> Rect:
    middle = work.left + work.width // 2
    target = (
        Rect(work.left, work.top, middle, work.bottom)
        if side == "left"
        else Rect(middle, work.top, work.right, work.bottom)
    )
    return framed(target, outer, visible)


def framed(target: Rect, outer: Rect, visible: Rect) -> Rect:
    return Rect(
        target.left - (visible.left - outer.left),
        target.top - (visible.top - outer.top),
        target.right + (outer.right - visible.right),
        target.bottom + (outer.bottom - visible.bottom),
    )
