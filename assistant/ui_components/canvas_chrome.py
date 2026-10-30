"""Quiet native canvas chrome: the frameless window, floating toolbar and icon buttons."""

from collections.abc import Callable
from typing import override

lazy from PySide6 import QtCore, QtGui, QtWidgets
lazy from PySide6.QtCore import Qt

from assistant.ui_components.appearance import CANVAS_STYLE, Ink
from assistant.ui_components.controls import button
from assistant.ui_components.widgets import Window
from assistant.vector_icons import icon


def icon_button(name: str, tip: str, action: Callable[[], None]) -> QtWidgets.QToolButton:
    control = button("", action, tip=tip)
    control.setIcon(icon(name, Ink().foreground))
    control.setIconSize(QtCore.QSize(16, 16))
    control.setFixedSize(32, 32)
    return control


class CanvasFrame(Window):
    """The native window owns its frame and drag handle; contents have no tabs."""

    def __init__(self, close: Callable[[], None], navigate: Callable[[], None]) -> None:
        super().__init__("Workspace · Canvas", close, width=1280, height=880)
        self.navigate: Callable[[], None] = navigate
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet(CANVAS_STYLE)
        self.setMinimumSize(800, 560)

    @override
    def escaped(self) -> None:
        self.navigate()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.setBrush(QtGui.QColor("#18171e"))
        painter.setPen(QtGui.QPen(QtGui.QColor("#4a3c58"), 1))
        radius = 0 if self.isMaximized() else 18
        painter.drawRoundedRect(QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)


class CanvasToolbar(QtWidgets.QFrame):
    """One floating control surface; its padding doubles as a native drag handle."""

    def __init__(self, parent: QtWidgets.QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("canvasPill")
        self.setAccessibleName("Canvas controls")
        self.setToolTip("Drag the toolbar background to move the window")

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() is Qt.MouseButton.LeftButton:
            self.window().windowHandle().startSystemMove()
            event.accept()
        else:
            super().mousePressEvent(event)


class CanvasSurface(QtWidgets.QWidget):
    """Notify the canvas owner to position floating controls after native resize."""

    resized = QtCore.Signal()

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        self.resized.emit()
