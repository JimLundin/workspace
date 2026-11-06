"""The tray icon: a coloured dot whose colour says what the assistant is doing."""

import math


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
