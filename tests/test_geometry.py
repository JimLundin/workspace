"""Window placement and screenshot coordinates."""

from contracts.geometry import half
from winapi.shapes import Rect

WORK = Rect(0, 0, 1920, 1040)  # a 1080p monitor, minus the taskbar


def test_half_fills_one_side_of_the_work_area_counting_invisible_borders() -> None:
    # Windows 10/11 windows have ~7px invisible borders around what's drawn.
    outer, visible = Rect(100, 100, 914, 708), Rect(107, 100, 907, 701)
    assert half(WORK, "left", outer, visible) == Rect(-7, 0, 967, 1047)
    assert half(WORK, "right", outer, visible) == Rect(953, 0, 1927, 1047)
