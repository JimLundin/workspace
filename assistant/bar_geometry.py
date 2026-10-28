"""Screen-edge shoulders and shallow joints, independent of either rendering backend."""

from dataclasses import dataclass

from winapi.contours import Contour, Curve, End, Line, Move

SHOULDER = 12
OVERLAP = 12
JOINT_DEPTH = 6


@dataclass(frozen=True, slots=True)
class Segment:
    fill: Contour
    edge: Contour


def segment(width: float, height: float, *, left: bool = False, right: bool = False) -> Segment:
    """Joined halves meet without overlapping tint, or drawing an edge across their seam."""
    shoulder = min(SHOULDER, width / 4, height / 2)
    bottom = min(8, height / 3)
    inset = OVERLAP / 2
    lx, rx = inset if left else 0, width - (inset if right else 0)
    ly, ry = JOINT_DEPTH if left else 0, JOINT_DEPTH if right else 0
    # Both renderers consume these exact cubic curves. The straight top and
    # vertical joining edges belong to the fill only, never to the outline.
    edge: Contour = (
        Move(rx, ry),
        Curve(width - shoulder, ry, width - shoulder, ry + shoulder / 2, width - shoulder, ry + shoulder),
        Line(width - shoulder, height - bottom),
        Curve(width - shoulder, height - bottom / 2, width - shoulder - bottom / 2, height, width - shoulder - bottom, height),
        Line(shoulder + bottom, height),
        Curve(shoulder + bottom / 2, height, shoulder, height - bottom / 2, shoulder, height - bottom),
        Line(shoulder, ly + shoulder),
        Curve(shoulder, ly + shoulder / 2, shoulder, ly, lx, ly),
    )
    fill: Contour = (Move(lx, 0), Line(rx, 0), Line(rx, ry), *edge[1:], Line(lx, 0), End.CLOSE)
    return Segment(fill, edge)
