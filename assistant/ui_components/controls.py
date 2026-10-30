"""Shared native panel controls. Qt objects stay on the UI thread."""

from collections.abc import Callable

lazy from PySide6 import QtWidgets
lazy from PySide6.QtCore import Qt

from assistant.qt_runtime import prepare

prepare()


def button(text: str, callback: Callable[[], None], *, tip: str = "", name: str = "") -> QtWidgets.QToolButton:
    widget = QtWidgets.QToolButton()
    widget.setText(text)
    widget.setAccessibleName(tip or text)
    widget.setToolTip(tip)
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    if name:
        widget.setObjectName(name)

    # Plain slotted controllers need not support weak references just because a
    # Qt signal owns a callback. Qt retains this small closure with the button.
    def clicked() -> None:
        callback()

    widget.clicked.connect(clicked)
    return widget


def label(text: str, name: str = "") -> QtWidgets.QLabel:
    widget = QtWidgets.QLabel(text)
    widget.setObjectName(name)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    return widget
