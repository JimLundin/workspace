"""Quiet native canvas chrome, using the desktop bubble's ink and lilac accents."""

from collections.abc import Callable
from typing import override

lazy from PySide6 import QtCore, QtGui, QtWidgets
lazy from PySide6.QtCore import Qt

from assistant.ui_components.bubble_style import Ink
from assistant.ui_components.controls import button
from assistant.ui_components.widgets import Window
from assistant.vector_icons import icon

CANVAS_STYLE = """
QWidget { color: #f6f3ff; font-family: 'Segoe UI'; font-size: 13px; background: transparent; }
QFrame#canvasPill { background: #25212f; border: 1px solid #494055; border-radius: 18px; }
QLabel { background: transparent; border: none; }
QLabel#muted { color: #a49aae; font-size: 11px; }
QLabel#title { font-size: 14px; font-weight: 600; }
QToolButton { border: 1px solid transparent; border-radius: 12px; padding: 5px 9px; background: transparent; }
QToolButton:hover { background: #3a3148; }
QToolButton:pressed { background: #4a3d5c; }
QToolButton:checked { background: #3a3148; }
QToolButton:focus { border-color: #ba9de3; }
QToolButton:disabled { color: #70677d; }
QToolButton#primary { background: #d9c8f3; color: #262131; font-weight: 600; padding: 7px 12px; }
QToolButton#primary:hover { background: #e6d8fa; }
QLineEdit, QPlainTextEdit, QComboBox { background: #211e29; border: 1px solid #4a405b; border-radius: 9px; padding: 7px; }
QLineEdit:focus, QPlainTextEdit:focus { border-color: #b697df; }
QPlainTextEdit:read-only { background: transparent; border: none; padding: 0; }
QLineEdit#canvasSearch { background: transparent; border: none; padding: 5px 8px; }
QComboBox QAbstractItemView { background: #292332; selection-background-color: #4a3a61; }
QMenu { background: #292332; border: 1px solid #574968; padding: 7px; }
QMenu::item { padding: 8px 20px; border-radius: 7px; }
QMenu::item:selected { background: #443454; }
QScrollBar:vertical { background: transparent; width: 5px; }
QScrollBar::handle:vertical { background: #665372; border-radius: 2px; min-height: 20px; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
QToolTip { background: #292332; color: #f6f3ff; border: 1px solid #675576; padding: 7px; }
"""


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
