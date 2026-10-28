"""Desktop observations and effects consumed by the keyboard overlay.

The overlay owns rendering and drag policy; this adapter owns native placement,
physical cursor observations and its persisted position.
"""

import time
from typing import Protocol

lazy from PySide6 import QtWidgets

from assistant.overlay import load_position, save_position
from assistant.qt_runtime import prepare
from winapi import inputs, screen, windows
from winapi.shapes import Rect

prepare()


class OverlayDesktop(Protocol):
    def clock(self) -> float: ...
    def cursor(self) -> tuple[int, int]: ...
    def work_areas(self) -> tuple[Rect, ...]: ...
    def load_position(self) -> tuple[int, int] | None: ...
    def save_position(self, position: tuple[int, int]) -> None: ...
    def prepare(self, window: QtWidgets.QWidget, *, click_through: bool) -> int: ...
    def present(self, window: QtWidgets.QWidget) -> None: ...
    def move(self, frame: int, area: Rect) -> None: ...


class NativeOverlayDesktop:
    def clock(self) -> float:
        return time.monotonic()

    def cursor(self) -> tuple[int, int]:
        return inputs.cursor_position()

    def work_areas(self) -> tuple[Rect, ...]:
        return tuple(monitor.work for monitor in screen.monitors())

    def load_position(self) -> tuple[int, int] | None:
        return load_position()

    def save_position(self, position: tuple[int, int]) -> None:
        save_position(position)

    def prepare(self, window: QtWidgets.QWidget, *, click_through: bool) -> int:
        frame = int(window.winId())
        windows.make_overlay(frame, click_through=click_through)
        return frame

    def present(self, window: QtWidgets.QWidget) -> None:
        window.show()
        windows.show_quietly(int(window.winId()), visible=True)

    def move(self, frame: int, area: Rect) -> None:
        windows.move(frame, area)
