"""The quiet layer indicator and its timed feedback capsule."""

lazy from PySide6 import QtCore, QtWidgets
lazy from PySide6.QtCore import Qt

from assistant.qt_runtime import prepare
from winapi import windows
from winapi.shapes import Rect
lazy from assistant.qt_ui import cancel, later
lazy from assistant.ui_components.appearance import GLASS_ACCENT, scheme, tokens
lazy from assistant.ui_components.controls import label
lazy from assistant.ui_components.widgets import row, surface, window_style

prepare()


class Indicator:
    __slots__ = (
        "__weakref__",
        "_flash",
        "_frame",
        "_ink",
        "_label",
        "_steady",
        "_window",
    )

    def __init__(self, root: QtWidgets.QApplication) -> None:
        theme = tokens(scheme())
        self._ink: str = theme.ink.css
        self._window = QtWidgets.QWidget()
        self._window.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
        self._window.setStyleSheet(window_style(theme))
        self._window.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._window.setWindowOpacity(0.9)
        # A 34 px capsule, as the island's.
        layout = row(surface(self._window, theme, 17))
        layout.setContentsMargins(16, 8, 16, 8)
        self._label = label("")
        layout.addWidget(self._label)
        self._frame = int(self._window.winId())
        windows.make_overlay(self._frame)
        self._steady: tuple[str | None, Rect] | None = None
        self._flash: QtCore.QTimer | None = None

    def _show(self, text: str | None, work: Rect, colour: str) -> None:
        if text is None:
            self._window.hide()
            return
        self._label.setText(text)
        self._label.setStyleSheet(f"color: {colour}; font-size: 13px; font-weight: 500;")
        self._window.adjustSize()
        scale = self._window.devicePixelRatioF()
        width, height = round(self._window.width() * scale), round(self._window.height() * scale)
        x, y = work.left + (work.width - width) // 2, work.bottom - height - 28
        windows.move(self._frame, Rect(x, y, x + width, y + height))
        self._window.show()
        windows.show_quietly(self._frame, visible=True)

    def set(self, text: str | None, work: Rect) -> None:
        self._steady = (text, work)
        if self._flash is None:
            self._show(text, work, self._ink)

    def flash(self, text: str, work: Rect, seconds: float) -> None:
        cancel(self._flash)
        self._show(text, work, GLASS_ACCENT)
        self._flash = later(self._window, round(seconds * 1000), self._end_flash)

    def _end_flash(self) -> None:
        self._flash = None
        if self._steady is not None:
            self._show(*self._steady, self._ink)
        else:
            self._window.hide()
