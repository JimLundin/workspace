"""The desktop's Qt application, its one-shot timers, and the bar's frame loop with its composition."""

import threading
from collections.abc import Callable
from dataclasses import dataclass, field

lazy import shiboken6
lazy from PySide6 import QtCore
lazy from PySide6.QtCore import QCoreApplication, QEvent
lazy from PySide6.QtWidgets import QApplication

from desktop_ui.qt_runtime import prepare
lazy from desktop_ui.components import typeface
lazy from winapi.composition import DesktopComposition

prepare()


def application(log: Callable[[str], None]) -> QApplication:
    existing = QApplication.instance()
    app = existing if isinstance(existing, QApplication) else QApplication([])
    app.setQuitOnLastWindowClosed(False)
    typeface.load(log)
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
class EventLoop:
    """The bar's frame timer and the desktop composition its glass draws in."""

    app: QApplication
    timer: QtCore.QTimer
    """Every frame while something moves; the bar connects its painting."""
    composition: DesktopComposition | None
    _closed: threading.Event = field(default_factory=threading.Event, init=False, repr=False)

    @classmethod
    def start(cls, app: QApplication, log: Callable[[str], None], frame: float) -> EventLoop:
        """The loop, framing every `frame` seconds; a composition that won't start goes to `log`."""
        timer = QtCore.QTimer(app)
        timer.setTimerType(QtCore.Qt.TimerType.PreciseTimer)
        timer.setInterval(round(frame * 1000))
        try:
            composition = DesktopComposition.start()
        except OSError as error:
            log(f"Desktop glass unavailable; using the solid material: {error}")
            composition = None
        return cls(app, timer, composition)

    @property
    def closed(self) -> bool:
        return self._closed.is_set()

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
        self._closed.set()
        self.timer.stop()
        self.timer.deleteLater()
        if self.composition is not None:
            self.composition.close(self.app.processEvents)
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
