"""Desktop observations consumed by the floating feed, separate from its UI."""

from typing import Protocol

from assistant.overlay import nearest_work_area
from winapi import inputs, screen, windows
from winapi.shapes import Rect


class Desktop(Protocol):
    def cursor_position(self) -> tuple[int, int]: ...

    def work_area(self, preferred: Rect | None) -> Rect: ...


class NativeDesktop:
    __slots__ = ()

    def cursor_position(self) -> tuple[int, int]:
        return inputs.cursor_position()

    def work_area(self, preferred: Rect | None) -> Rect:
        if preferred is None:
            return screen.monitor_of(windows.foreground()).work
        areas = tuple(monitor.work for monitor in screen.monitors())
        return nearest_work_area((preferred.left, preferred.top), areas)
