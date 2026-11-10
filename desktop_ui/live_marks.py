"""The live marks an activity draws: the microphone's trace and a quick job's pulsing dots.

The bar draws them in its capsules and the dictation marker beside the caret,
each at the sizes its capsule declares.
"""

import math
from collections.abc import Iterable
from dataclasses import dataclass

lazy from PySide6 import QtCore, QtGui
lazy from PySide6.QtCore import Qt

from desktop_ui.components.appearance import Shade
from desktop_ui.components.text import color
from desktop_ui.island_layout import Capsule, Markers


@dataclass(frozen=True, slots=True)
class Beat:
    """Where the dots' pulse is in its cycle, from 0 to 1."""

    cycle: float
    lag: float
    """How far each dot's pulse trails the one before, in cycles."""
    resting: float
    """A dot's opacity at rest, as a share of its ink's."""


def paint_wave(painter: QtGui.QPainter, start: QtCore.QPointF, trace: Iterable[float], capsule: Capsule, markers: Markers) -> None:
    """One bar per sample from `start`, centred on its height, in the painter's brush."""
    painter.setPen(Qt.PenStyle.NoPen)
    pitch, corner = capsule.wave_bar + capsule.wave_gap, markers.wave_corner
    for index, sample in enumerate(trace):
        height = markers.wave_floor + sample * markers.wave_reach
        painter.drawRoundedRect(QtCore.QRectF(start.x() + index * pitch, start.y() - height / 2, capsule.wave_bar, height), corner, corner)


def paint_dots(painter: QtGui.QPainter, room: QtCore.QRectF, beat: Beat, markers: Markers, ink: Shade) -> None:
    """Dots pulsing in turn, each centred in an equal share of `room`'s width."""
    pitch, radius, middle = room.width() / markers.dot_count, markers.dots_radius, room.center().y()
    painter.setPen(Qt.PenStyle.NoPen)
    for index in range(markers.dot_count):
        lift = max(0.0, math.sin((beat.cycle - index * beat.lag) * 2 * math.pi))
        painter.setBrush(color(Shade(ink.color, ink.opacity * (beat.resting + (1 - beat.resting) * lift))))
        painter.drawEllipse(QtCore.QPointF(room.left() + pitch * (index + 0.5), middle - lift * markers.dots_lift), radius, radius)
