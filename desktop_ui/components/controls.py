from collections.abc import Callable

lazy from PySide6 import QtWidgets
lazy from PySide6.QtCore import Qt

from desktop_ui.qt_runtime import prepare

prepare()


def button(text: str, callback: Callable[[], None]) -> QtWidgets.QToolButton:
    widget = QtWidgets.QToolButton()
    widget.setText(text)
    widget.setAccessibleName(text)
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def clicked() -> None:
        callback()

    widget.clicked.connect(clicked)
    return widget


def label(text: str, name: str = "") -> QtWidgets.QLabel:
    widget = QtWidgets.QLabel(text)
    widget.setObjectName(name)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    return widget
