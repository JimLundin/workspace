"""Shared Qt controls, selection-preserving text updates and native window behavior."""

import threading
from collections.abc import Callable, Sequence

lazy from PySide6 import QtCore, QtGui, QtWidgets
lazy from PySide6.QtCore import Qt

from assistant.qt_runtime import prepare
from assistant.ui_components.appearance import GLASS_ACCENT, Scheme, Shade, Tokens, control_style, scheme, tokens
from assistant.vector_icons import icon
from winapi import windows

prepare()


def window_style(theme: Tokens) -> str:
    """The shared controls on the kit's solid window: reading on a solid card, filled buttons, the default action in the accent, segmented choices."""
    thumb = "rgba(255,255,255,56)" if theme.scheme is Scheme.DARK else theme.solid
    return (
        control_style(theme)
        + f"""
QWidget#workspaceWindow {{ background: {theme.window}; }}
QPushButton:default {{ background: {GLASS_ACCENT}; color: #ffffff; font-weight: 600; }}
QPushButton:default:hover {{ background: #6aa2ec; }}
QDialogButtonBox QPushButton, QToolButton#filled, QPushButton#filled {{ background: {theme.hover.css}; }}
QDialogButtonBox QPushButton:hover, QToolButton#filled:hover, QPushButton#filled:hover {{ background: {theme.press.css}; }}
QWidget#workspaceWindow QPlainTextEdit:read-only {{
 background: {theme.solid}; border: 1px solid {theme.solid_edge.css}; border-radius: 14px; padding: 10px 12px;
}}
QFrame#segmented {{ background: {theme.hover.css}; border-radius: 10px; }}
QFrame#segmented QToolButton {{ border-radius: 8px; padding: 4px 12px; min-height: 18px; font-size: 12px; }}
QFrame#segmented QToolButton:focus {{ padding: 2px 10px; }}
QFrame#segmented QToolButton:checked {{ background: {thumb}; }}
"""
    )


def surface_style(theme: Tokens, radius: int) -> str:
    """A solid surface from the kit: the window colour, a hairline edge and large concentric corners."""
    return f"QFrame#surface {{ background: {theme.window}; border: 1px solid {theme.solid_edge.css}; border-radius: {radius}px; }}"


def surface(window: QtWidgets.QWidget, theme: Tokens, radius: int) -> QtWidgets.QFrame:
    """Draw a frameless window as one rounded surface; its corners stay transparent."""
    window.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    frame = QtWidgets.QFrame(window)
    frame.setObjectName("surface")
    frame.setStyleSheet(surface_style(theme, radius))
    column(window).addWidget(frame)
    return frame


def segmented(buttons: Sequence[QtWidgets.QToolButton]) -> QtWidgets.QFrame:
    """Checkable choices in one well; the checked choice carries the thumb."""
    frame = QtWidgets.QFrame()
    frame.setObjectName("segmented")
    layout = row(frame)
    layout.setContentsMargins(2, 2, 2, 2)
    layout.setSpacing(2)
    for choice in buttons:
        layout.addWidget(choice)
    return frame


def glyph(name: str, ink: Shade, size: int = 16) -> QtGui.QPixmap:
    """A symbol in translucent ink, such as the secondary ink; SVG fills take no alpha."""
    solid = icon(name, ink.color, size).pixmap(QtCore.QSize(size, size))
    faded = QtGui.QPixmap(solid.size())
    faded.setDevicePixelRatio(solid.devicePixelRatio())
    faded.fill(Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(faded)
    painter.setOpacity(ink.opacity)
    painter.drawPixmap(0, 0, solid)
    painter.end()
    return faded


class Window(QtWidgets.QWidget):
    geometry_changed = QtCore.Signal()

    def __init__(self, title: str, close: Callable[[], None], *, width: int = 900, height: int = 640) -> None:
        super().__init__()
        self.on_close = close
        self.setObjectName("workspaceWindow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setWindowTitle(title)
        self.setStyleSheet(window_style(tokens(scheme())))
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.resize(width, height)
        self.escape = QtGui.QShortcut(QtGui.QKeySequence("Escape"), self)

        self.escape.activated.connect(self.escaped)

    def escaped(self) -> None:
        self.on_close()

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        event.ignore()
        self.on_close()

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        self.geometry_changed.emit()


def show_window(window: QtWidgets.QWidget, *, focus: bool, target: QtWidgets.QWidget | None = None, topmost: bool = False) -> None:
    handle = int(window.winId())
    windows.allow_activation(handle, allowed=False)
    try:
        window.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        window.show()
        windows.show_quietly(handle, visible=True, topmost=topmost)
        # Qt's first quiet show can leave a maximized widget at normal native
        # geometry. Apply its requested state while activation is still blocked.
        if window.isMaximized() and not windows.is_maximized(handle):
            windows.show(handle, windows.SW_MAXIMIZE)
    finally:
        windows.allow_activation(handle, allowed=True)
    if focus:
        threading.Thread(target=lambda: windows.focus(handle), name="focus workspace", daemon=True).start()
        (target or window).setFocus(Qt.FocusReason.OtherFocusReason)


class Editor(QtWidgets.QPlainTextEdit):
    submitted = QtCore.Signal()
    painted = QtCore.Signal()

    def __init__(self, parent: QtWidgets.QWidget | None = None, *, readonly: bool = False, enter_sends: bool = False) -> None:
        super().__init__(parent)
        self.enter_sends = enter_sends
        self.setReadOnly(readonly)
        self.setTabChangesFocus(True)
        self.setMinimumHeight(60)

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        enter = event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
        send = (
            not bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            if self.enter_sends
            else bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
        )
        if enter and send and not self.isReadOnly():
            self.submitted.emit()
            event.accept()
        else:
            super().keyPressEvent(event)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        super().paintEvent(event)
        self.painted.emit()


class Browser(QtWidgets.QTextBrowser):
    painted = QtCore.Signal()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        super().paintEvent(event)
        self.painted.emit()


def replace_text(widget: QtWidgets.QPlainTextEdit, value: str) -> None:
    if widget.toPlainText() == value:
        return
    cursor = widget.textCursor()
    anchor, position, selected = cursor.anchor(), cursor.position(), cursor.selectedText()
    scroll = widget.verticalScrollBar().value()
    widget.setPlainText(value)
    maximum = widget.document().characterCount() - 1
    cursor.setPosition(min(anchor, maximum))
    cursor.setPosition(min(position, maximum), QtGui.QTextCursor.MoveMode.KeepAnchor)
    if cursor.selectedText() == selected:
        widget.setTextCursor(cursor)
    widget.verticalScrollBar().setValue(scroll)


def row(parent: QtWidgets.QWidget | None = None) -> QtWidgets.QHBoxLayout:
    layout = QtWidgets.QHBoxLayout(parent) if parent is not None else QtWidgets.QHBoxLayout()
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)
    return layout


def column(parent: QtWidgets.QWidget | None = None) -> QtWidgets.QVBoxLayout:
    layout = QtWidgets.QVBoxLayout(parent) if parent is not None else QtWidgets.QVBoxLayout()
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(10)
    return layout
