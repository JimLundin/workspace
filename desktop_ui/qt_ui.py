"""One Qt event loop and Windows composition lifetime for all assistant views."""

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Final

lazy import shiboken6
lazy from PySide6 import QtCore
lazy from PySide6.QtCore import QCoreApplication, QEvent
lazy from PySide6.QtWidgets import QApplication

from cell import Cell
from desktop_ui.qt_runtime import prepare
lazy from desktop_ui.components import typeface
lazy from desktop_ui.view_publication import log_view
lazy from winapi import screen
lazy from winapi.composition import DesktopComposition
lazy from winapi.shapes import Rect

prepare()


def application() -> QApplication:
    existing = QApplication.instance()
    app = existing if isinstance(existing, QApplication) else QApplication([])
    app.setQuitOnLastWindowClosed(False)
    typeface.load()
    return app


def later(parent: QtCore.QObject, milliseconds: int, callback: Callable[[], None]) -> QtCore.QTimer:
    """Schedule one UI-owned callback. Closing its owner cancels delivery."""
    timer = QtCore.QTimer(parent)
    timer.setTimerType(QtCore.Qt.TimerType.PreciseTimer)
    timer.setSingleShot(True)

    def deliver() -> None:
        timer.deleteLater()
        callback()

    timer.timeout.connect(deliver)
    timer.start(milliseconds)
    return timer


def cancel(timer: QtCore.QTimer | None) -> None:
    if timer is not None and shiboken6.isValid(timer):
        timer.stop()
        timer.deleteLater()


@dataclass(frozen=True, slots=True)
class _Shared:
    """The desktop composition every event loop shares, and how many loops use it."""

    users: int = 0
    composition: DesktopComposition | None = None


_SHARED: Final = Cell(_Shared())
"""Replaced as loops start and close, on the Qt thread."""


@dataclass(frozen=True, slots=True)
class EventLoop:
    app: QApplication
    painted: Callable[[], None]
    timer: QtCore.QTimer
    composition: DesktopComposition | None
    _closed: Cell[bool] = field(default_factory=lambda: Cell(False), init=False, repr=False)

    @classmethod
    def start(cls, app: QApplication, painted: Callable[[], None]) -> EventLoop:
        timer = QtCore.QTimer(app)
        timer.setTimerType(QtCore.Qt.TimerType.PreciseTimer)
        timer.setInterval(16)
        timer.timeout.connect(painted)
        shared = _SHARED.get()
        if shared.users == 0:
            try:
                shared = replace(shared, composition=DesktopComposition.start())
            except OSError as error:
                log_view(f"Desktop glass unavailable; using the solid material: {error}")
        _SHARED.set(replace(shared, users=shared.users + 1))
        return cls(app, painted, timer, shared.composition)

    @property
    def closed(self) -> bool:
        return self._closed.get()

    def pump(self) -> None:
        self.app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        if not self.closed:
            self.painted()

    def scale(self, work: Rect) -> float:
        area = next((monitor.area for monitor in screen.monitors() if work.top_left in monitor.area), None)
        target = next(
            (
                display
                for display in self.app.screens()
                if area is not None and (display.geometry().left(), display.geometry().top()) == (area.left, area.top)
            ),
            self.app.primaryScreen(),
        )
        return target.devicePixelRatio()

    def watch(self, *, visible: bool) -> None:
        if not self.closed:
            # Observations and paint callbacks must preserve the next frame's
            # deadline. Restarting an active timer lets frequent updates starve it.
            if visible and not self.timer.isActive():
                self.timer.start()
            elif not visible:
                self.timer.stop()

    def close(self) -> None:
        if self.closed:
            return
        self._closed.set(True)
        self.timer.stop()
        self.timer.deleteLater()
        shared = _SHARED.get()
        users = shared.users - 1
        if users == 0 and shared.composition is not None:
            shared.composition.close(self.app.processEvents)
            shared = replace(shared, composition=None)
        _SHARED.set(replace(shared, users=users))
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
