"""Desktop observations and effects consumed by the keyboard overlay.

The overlay owns rendering and drag policy; this adapter owns native placement,
and physical cursor observations; the overlay keeps its own position.
"""

import time
from dataclasses import dataclass

lazy from PySide6 import QtWidgets

from desktop_ui.qt_runtime import prepare
from winapi import inputs, screen, windows
from winapi.shapes import Point, Rect

prepare()


@dataclass(frozen=True, slots=True)
class NativeOverlayDesktop:
    def clock(self) -> float:
        return time.monotonic()

    def cursor(self) -> Point:
        return inputs.cursor_position()

    def work_areas(self) -> tuple[Rect, ...]:
        return tuple(monitor.work for monitor in screen.monitors())

    def prepare(self, window: QtWidgets.QWidget, *, click_through: bool) -> int:
        frame = int(window.winId())
        windows.make_overlay(frame, click_through=click_through)
        return frame

    def present(self, window: QtWidgets.QWidget) -> None:
        window.show()
        windows.show_quietly(int(window.winId()), visible=True)

    def move(self, frame: int, area: Rect) -> None:
        windows.move(frame, area)
