"""Shared Qt controls, selection-preserving text updates and native window behavior."""

import threading
from collections.abc import Callable

lazy from PySide6 import QtCore, QtGui, QtWidgets
lazy from PySide6.QtCore import Qt

from assistant.qt_runtime import prepare
from assistant.ui_components.appearance import CONTROL_STYLE
from winapi import windows

prepare()


class Window(QtWidgets.QWidget):
    geometry_changed = QtCore.Signal()

    def __init__(self, title: str, close: Callable[[], None], *, width: int = 900, height: int = 640) -> None:
        super().__init__()
        self.on_close = close
        self.setObjectName("workspaceWindow")
        self.setWindowTitle(title)
        self.setStyleSheet(CONTROL_STYLE)
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
