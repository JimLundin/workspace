"""Native dialog placement and presentation on the owning Qt thread."""

from typing import Protocol

lazy from PySide6 import QtGui, QtWidgets

from assistant.qt_runtime import prepare
lazy from assistant.ui_components.widgets import show_window

prepare()


def bring_forward(window: QtWidgets.QWidget, focus: QtWidgets.QWidget) -> None:
    show_window(window, focus=True, target=focus)


def near_pointer(window: QtWidgets.QWidget, width: int, height: int) -> None:
    point = QtGui.QCursor.pos()
    display = QtWidgets.QApplication.screenAt(point) or window.screen()
    area = display.availableGeometry()
    window.resize(width, height)
    window.move(
        max(area.left(), min(point.x() - width // 2, area.right() - width)), max(area.top(), min(point.y() - height // 3, area.bottom() - height))
    )


class Presentation(Protocol):
    """Position and reveal native dialogs on their owning Qt thread."""

    def position(self, window: QtWidgets.QWidget, width: int, height: int) -> None: ...

    def reveal(self, window: QtWidgets.QWidget, focus: QtWidgets.QWidget) -> None: ...


class NativePresentation:
    __slots__ = ()

    def position(self, window: QtWidgets.QWidget, width: int, height: int) -> None:
        near_pointer(window, width, height)

    def reveal(self, window: QtWidgets.QWidget, focus: QtWidgets.QWidget) -> None:
        bring_forward(window, focus)
