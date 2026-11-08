"""Native shell behavior with isolated views and controlled Windows boundaries."""

import sys
import unittest

if sys.platform != "win32":
    raise unittest.SkipTest("Windows desktop shell")

lazy from PySide6 import QtCore, QtGui

from desktop_ui.qt_runtime import prepare
from desktop_ui.qt_ui import application
lazy from desktop_ui.window_switcher import WindowSwitcher
lazy from winapi.shapes import Window

prepare()


def test_window_switcher_search_navigation_and_activation() -> None:
    app = application()
    focused: list[int] = []
    picker = WindowSwitcher(
        (
            Window(1, "Editor · current", "editor.exe", minimized=False),
            Window(2, "Planning board", "browser.exe", minimized=False),
            Window(3, "Archived planning", "browser.exe", minimized=True),
        ),
        focused.append,
    )
    try:
        assert picker.items.currentRow() == 1  # F6 defaults to the previous window.
        picker.search.setText("planning browser")
        assert picker.items.count() == 2
        key = QtGui.QKeyEvent(QtCore.QEvent.Type.KeyPress, QtCore.Qt.Key.Key_Down, QtCore.Qt.KeyboardModifier.NoModifier)
        assert picker.eventFilter(picker.search, key)
        assert picker.items.currentRow() == 1
        picker.activate()
        assert focused == [3]
        picker.filter("no such window")
        picker.activate()
        assert focused == [3]
    finally:
        picker.close()
        app.processEvents()
