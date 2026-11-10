"""The tray icon: a coloured dot whose colour says what the assistant is doing."""

import math

from desktop_ui.colour import Rgb


def dot(size: int, colour: Rgb) -> bytes:
    """A filled circle with a soft edge on a transparent square: BGRA, top row first."""
    r, g, b = colour.red, colour.green, colour.blue
    centre, radius = (size - 1) / 2, size * 0.42
    return bytes(
        channel
        for y in range(size)
        for x in range(size)
        for coverage in (min(max(radius - math.hypot(x - centre, y - centre) + 0.5, 0.0), 1.0),)
        for channel in ((b, g, r, round(255 * coverage)) if coverage else (0, 0, 0, 0))
    )
