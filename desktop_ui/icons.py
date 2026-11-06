"""The tray icon: a coloured dot whose colour says what the assistant is doing."""

import math
from typing import assert_never

from contracts.status import State


def colour(state: State) -> tuple[int, int, int]:
    """The tray dot's colour (red, green, blue) for what the assistant is doing."""
    match state:
        case State.READY:
            return (46, 160, 120)
        case State.LAYOUT_OFF:
            return (140, 140, 140)
        case State.LISTENING:
            return (220, 50, 50)
        case State.RECORDING:
            return (230, 64, 85)
        case State.WORKING:
            return (235, 160, 30)
        case State.AGENT:
            return (60, 120, 230)
        case State.NEEDS_INPUT:
            return (230, 185, 75)
        case _:
            assert_never(state)


def dot(size: int, rgb: tuple[int, int, int]) -> bytes:
    """A filled circle with a soft edge on a transparent square: BGRA, top row first."""
    r, g, b = rgb
    centre, radius = (size - 1) / 2, size * 0.42
    pixels = bytearray(size * size * 4)
    for y in range(size):
        for x in range(size):
            coverage = min(max(radius - math.hypot(x - centre, y - centre) + 0.5, 0.0), 1.0)
            if coverage:
                i = (y * size + x) * 4
                pixels[i : i + 4] = bytes((b, g, r, round(255 * coverage)))
    return bytes(pixels)
