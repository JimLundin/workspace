"""Quiet native canvas chrome: the content window, its floating glass capsules and the scroll edge."""

from collections.abc import Callable
from typing import override

lazy from PySide6 import QtCore, QtGui, QtWidgets
lazy from PySide6.QtCore import Qt

from assistant.ui_components.appearance import GLASS_ACCENT, Tokens, canvas_style
from assistant.ui_components.canvas_look import CAPSULE, CONTROL, SHADOW, WINDOW_RADIUS, glass_ink, paint_glass, paint_scroll_edge
from assistant.ui_components.controls import button
from assistant.ui_components.meaning import Tint
from assistant.ui_components.text import color
from assistant.ui_components.widgets import Window, row
from assistant.vector_icons import icon


def content_style(theme: Tokens) -> str:
    """The canvas's controls and details; inside solid cards, buttons are filled, never glass."""
    return canvas_style(theme) + (
        f"QToolButton {{ background: {theme.hover.css}; }} QToolButton:hover {{ background: {theme.press.css}; }}"
        f" QToolButton:pressed {{ background: {theme.press.css}; }}"
    )


class CanvasFrame(Window):
    """The native window owns its frame and drag handle; contents have no tabs.

    A neutral solid content window with the kit's large corners while restored.
    """

    def __init__(self, close: Callable[[], None], navigate: Callable[[], None], theme: Tokens) -> None:
        super().__init__("Workspace · Canvas", close, width=1280, height=880)
        self.navigate: Callable[[], None] = navigate
        self.theme: Tokens = theme
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet(content_style(theme))
        self.setMinimumSize(800, 560)

    @override
    def escaped(self) -> None:
        self.navigate()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.setBrush(QtGui.QColor(self.theme.window))
        painter.setPen(QtGui.QPen(color(self.theme.separator), 1))
        radius = 0 if self.isMaximized() else WINDOW_RADIUS
        painter.drawRoundedRect(QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)


class GlassCapsule(QtWidgets.QFrame):
    """A floating glass capsule over the canvas, holding concentric 28 px controls.

    Its margins hold the shadow, so the glass itself is inset from the widget.
    """

    def __init__(self, parent: QtWidgets.QWidget, theme: Tokens, tint: Tint) -> None:
        super().__init__(parent)
        self.theme: Tokens = theme
        self.tint: Tint = tint
        inset = (CAPSULE - CONTROL) // 2
        self.setContentsMargins(SHADOW.left() + inset, SHADOW.top() + inset, SHADOW.right() + inset, SHADOW.bottom() + inset)
        self.content: QtWidgets.QHBoxLayout = row(self)
        self.content.setSpacing(2)
        ink = glass_ink(theme, tint)
        # Qt sizes a styled button's contents box: 24 px inside a 2 px border keeps the 28 px circle.
        self.setStyleSheet(
            f"QToolButton#glass {{ border: 2px solid transparent; border-radius: {CONTROL // 2}px; padding: 0; background: transparent;"
            f" min-height: {CONTROL - 4}px; max-height: {CONTROL - 4}px; min-width: {CONTROL - 4}px; max-width: {CONTROL - 4}px;"
            f" color: {ink.ink.css}; font-size: 12px; font-weight: 500; }}"
            f' QToolButton#glass[caption="true"] {{ padding: 0 10px 0 8px; max-width: 160px; }}'
            f" QToolButton#glass:hover {{ background: {ink.hover.css}; }}"
            f" QToolButton#glass:pressed, QToolButton#glass:checked {{ background: {ink.press.css}; }}"
            f" QToolButton#glass:focus {{ border-color: {GLASS_ACCENT}; }}"
        )

    def glass(self) -> QtCore.QRectF:
        return QtCore.QRectF(self.rect()).marginsRemoved(QtCore.QMarginsF(SHADOW))

    def button(self, symbol: str, tip: str, action: Callable[[], None]) -> QtWidgets.QToolButton:
        control = button("", action, tip=tip, name="glass")
        control.setIcon(icon(symbol, glass_ink(self.theme, self.tint).ink.color))
        control.setIconSize(QtCore.QSize(16, 16))
        return control

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        paint_glass(painter, self.glass(), self.theme, self.tint)
        painter.end()


class CanvasToolbar(GlassCapsule):
    """The canvas's island: one glass capsule whose background doubles as a native drag handle."""

    def __init__(self, parent: QtWidgets.QWidget, theme: Tokens) -> None:
        super().__init__(parent, theme, Tint.NONE)
        self.setAccessibleName("Canvas controls")
        self.setToolTip("Drag the toolbar background to move the window")

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() is Qt.MouseButton.LeftButton and self.glass().contains(event.position()):
            self.window().windowHandle().startSystemMove()
            event.accept()
        else:
            super().mousePressEvent(event)


class ScrollEdge(QtWidgets.QWidget):
    """The soft scroll edge where content passes beneath the floating toolbar; it never takes the pointer."""

    def __init__(self, parent: QtWidgets.QWidget, theme: Tokens) -> None:
        super().__init__(parent)
        self.theme: Tokens = theme
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        paint_scroll_edge(painter, QtCore.QRectF(self.rect()), self.theme)
        painter.end()


class CanvasSurface(QtWidgets.QWidget):
    """Notify the canvas owner to position floating controls after native resize."""

    resized = QtCore.Signal()

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        self.resized.emit()
