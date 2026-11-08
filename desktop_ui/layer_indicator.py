"""The quiet layer indicator and its timed feedback capsule."""

from dataclasses import dataclass, field, replace

lazy from PySide6 import QtCore, QtWidgets

from cell import Cell
from desktop_ui.qt_runtime import prepare
from winapi import windows
from winapi.shapes import Rect
lazy from desktop_ui.components.appearance import GLASS_ACCENT, scheme, tokens
lazy from desktop_ui.components.controls import label
lazy from desktop_ui.components.widgets import device_size, row, surface, tool_window, window_style
lazy from desktop_ui.qt_ui import cancel, later

prepare()


@dataclass(frozen=True, slots=True)
class _Shown:
    steady: tuple[str | None, Rect] | None = None
    """What the indicator shows between flashes."""
    flash: QtCore.QTimer | None = None
    """The timer ending a flash in progress."""


@dataclass(frozen=True, slots=True, weakref_slot=True)
class Indicator:
    _ink: str
    _window: QtWidgets.QWidget
    _label: QtWidgets.QLabel
    _frame: int
    _shown: Cell[_Shown] = field(default_factory=lambda: Cell(_Shown()), init=False, repr=False)

    @classmethod
    def build(cls, _root: QtWidgets.QApplication) -> Indicator:
        theme = tokens(scheme())
        window = QtWidgets.QWidget()
        tool_window(window, None, on_top=False)
        window.setStyleSheet(window_style(theme))
        window.setWindowOpacity(0.9)
        # A 34 px capsule, as the island's.
        layout = row(surface(window, theme, 17))
        layout.setContentsMargins(16, 8, 16, 8)
        text = label("")
        layout.addWidget(text)
        frame = int(window.winId())
        windows.make_overlay(frame)
        return cls(theme.ink.css, window, text, frame)

    def _show(self, text: str | None, work: Rect, colour: str) -> None:
        if text is None:
            self._window.hide()
            return
        self._label.setText(text)
        self._label.setStyleSheet(f"color: {colour}; font-size: 13px; font-weight: 500;")
        self._window.adjustSize()
        size = device_size(self._window, self._window.devicePixelRatioF())
        x, y = work.left + (work.width - size.width) // 2, work.bottom - size.height - 28
        windows.move(self._frame, Rect(x, y, x + size.width, y + size.height))
        self._window.show()
        windows.show_quietly(self._frame, visible=True)

    def set(self, text: str | None, work: Rect) -> None:
        shown = self._shown.update(lambda shown: replace(shown, steady=(text, work)))
        if shown.flash is None:
            self._show(text, work, self._ink)

    def flash(self, text: str, work: Rect, seconds: float) -> None:
        cancel(self._shown.get().flash)
        self._show(text, work, GLASS_ACCENT)
        timer = later(self._window, round(seconds * 1000), self._end_flash)
        self._shown.update(lambda shown: replace(shown, flash=timer))

    def _end_flash(self) -> None:
        shown = self._shown.update(lambda shown: replace(shown, flash=None))
        if shown.steady is not None:
            self._show(*shown.steady, self._ink)
        else:
            self._window.hide()
