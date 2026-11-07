"""The tray icon: a coloured dot whose colour says what the assistant is doing."""

import math
from typing import Final

from contracts.members import every_member
from contracts.status import State
from desktop_ui.colour import Rgb

COLOURS: Final[frozendict[State, Rgb]] = every_member(
    State,
    {
        State.READY: Rgb(46, 160, 120),
        State.LAYOUT_OFF: Rgb(140, 140, 140),
        State.LISTENING: Rgb(220, 50, 50),
        State.RECORDING: Rgb(230, 64, 85),
        State.WORKING: Rgb(235, 160, 30),
        State.AGENT: Rgb(60, 120, 230),
        State.NEEDS_INPUT: Rgb(230, 185, 75),
    },
)
"""The tray dot's colour for each thing the assistant can be doing."""


def dot(size: int, colour: Rgb) -> bytes:
    """A filled circle with a soft edge on a transparent square: BGRA, top row first."""
    r, g, b = colour.red, colour.green, colour.blue
    centre, radius = (size - 1) / 2, size * 0.42
    pixels = bytearray(size * size * 4)
    for y in range(size):
        for x in range(size):
            coverage = min(max(radius - math.hypot(x - centre, y - centre) + 0.5, 0.0), 1.0)
            if coverage:
                i = (y * size + x) * 4
                pixels[i : i + 4] = bytes((b, g, r, round(255 * coverage)))
    return bytes(pixels)
