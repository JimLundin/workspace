"""Qt-thread jobs and placing native windows in front of the user."""

from collections.abc import Callable

lazy from PySide6 import QtGui, QtWidgets

from desktop_ui.qt_runtime import prepare

prepare()


type Job = Callable[[QtWidgets.QApplication], None]


def near_pointer(window: QtWidgets.QWidget, width: int, height: int) -> None:
    point = QtGui.QCursor.pos()
    display = QtWidgets.QApplication.screenAt(point) or window.screen()
    area = display.availableGeometry()
    window.resize(width, height)
    window.move(
        max(area.left(), min(point.x() - width // 2, area.right() - width)), max(area.top(), min(point.y() - height // 3, area.bottom() - height))
    )
