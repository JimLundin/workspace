"""A one-shot native presentation acknowledgement after a real widget paint."""

from collections.abc import Callable
from typing import override

lazy from PySide6 import QtCore, QtWidgets

from assistant.qt_ui import cancel, later


class PaintReady(QtCore.QObject):
    """Qt owns this filter and timer; only the first paint schedules completion."""

    def __init__(self, widget: QtWidgets.QWidget, ready: Callable[[], None]) -> None:
        super().__init__(widget)
        self.widget: QtWidgets.QWidget = widget
        self.ready: Callable[[], None] | None = ready
        self.timer: QtCore.QTimer | None = None
        widget.installEventFilter(self)

    @override
    def eventFilter(self, watched: QtCore.QObject, event: QtCore.QEvent) -> bool:
        if event.type() == QtCore.QEvent.Type.Paint and self.ready is not None and self.timer is None:
            self.widget.removeEventFilter(self)
            # The callback runs after Qt returns from painting and flushes the
            # backing store, rather than from inside a partially drawn frame.
            self.timer = later(self, 0, self.deliver)
        return False

    def deliver(self) -> None:
        self.timer = None
        ready, self.ready = self.ready, None
        if ready is not None:
            ready()

    def cancel(self) -> None:
        self.widget.removeEventFilter(self)
        cancel(self.timer)
        self.timer = None
        self.ready = None
