"""The quiet layer indicator and its timed feedback capsule."""

from dataclasses import dataclass, field, replace
from typing import Final

lazy from PySide6 import QtCore, QtWidgets

from cell import Cell
from desktop_ui.components.appearance import PALETTE
from desktop_ui.components.typeface import TYPE, Font
from desktop_ui.island_layout import SIZES
from desktop_ui.qt_runtime import prepare
from winapi import windows
from winapi.shapes import Rect
lazy from desktop_ui.components.appearance import Design
lazy from desktop_ui.components.controls import label
lazy from desktop_ui.components.widgets import device_size, row, surface, tool_window, window_style
lazy from desktop_ui.qt_ui import cancel, later

prepare()


@dataclass(frozen=True, slots=True, kw_only=True)
class IndicatorSpec:
    """The layer indicator: a capsule at the bottom of the work area that names the layer."""

    radius: float
    padding: float
    """Beside the text..."""
    leading: float
    """...and above and below it."""
    opacity: float
    font: Font
    bottom: int
    """From the work area's bottom edge."""
    flash: float
    """Seconds a change of layout stays lit before the steady layer returns."""
    flash_ink: str
    layout_on: str
    layout_off: str
    """What the indicator flashes as the layout switches on or off."""


INDICATOR: Final = IndicatorSpec(
    radius=SIZES.bar.radius,  # The island's capsule, so the two read as one family.
    padding=16,
    leading=8,
    opacity=0.9,
    font=TYPE.title,
    bottom=28,
    flash=1.2,
    flash_ink=PALETTE.accent,
    layout_on="Layout on",
    layout_off="Layout off",
)


@dataclass(frozen=True, slots=True)
class _Shown:
    steady: tuple[str | None, Rect] | None = None
    """What the indicator shows between flashes."""
    flash: QtCore.QTimer | None = None
    """The timer ending a flash in progress."""


@dataclass(frozen=True, slots=True, weakref_slot=True)
class Indicator:
    _spec: IndicatorSpec
    _ink: str
    _window: QtWidgets.QWidget
    _label: QtWidgets.QLabel
    _frame: int
    _shown: Cell[_Shown] = field(default_factory=lambda: Cell(_Shown()), init=False, repr=False)

    @classmethod
    def build(cls, spec: IndicatorSpec, design: Design) -> Indicator:
        theme = design.tokens()
        window = QtWidgets.QWidget()
        tool_window(window, None, on_top=False)
        window.setStyleSheet(window_style(theme, design))
        window.setWindowOpacity(spec.opacity)
        layout = row(surface(window, theme, round(spec.radius), design.kit))
        pad, lead = round(spec.padding), round(spec.leading)
        layout.setContentsMargins(pad, lead, pad, lead)
        text = label("")
        layout.addWidget(text)
        frame = int(window.winId())
        windows.make_overlay(frame)
        return cls(spec, theme.ink.css, window, text, frame)

    def _show(self, text: str | None, work: Rect, colour: str) -> None:
        if text is None:
            self._window.hide()
            return
        self._label.setText(text)
        self._label.setStyleSheet(f"color: {colour}; {self._spec.font.css}")
        self._window.adjustSize()
        size = device_size(self._window, self._window.devicePixelRatioF())
        x, y = work.left + (work.width - size.width) // 2, work.bottom - size.height - self._spec.bottom
        windows.move(self._frame, Rect(x, y, x + size.width, y + size.height))
        self._window.show()
        windows.show_quietly(self._frame, visible=True)

    def set(self, text: str | None, work: Rect) -> None:
        shown = self._shown.update(lambda shown: replace(shown, steady=(text, work)))
        if shown.flash is None:
            self._show(text, work, self._ink)

    def flash(self, text: str, work: Rect) -> None:
        cancel(self._shown.get().flash)
        self._show(text, work, self._spec.flash_ink)
        timer = later(self._window, round(self._spec.flash * 1000), self._end_flash)
        self._shown.update(lambda shown: replace(shown, flash=timer))

    def _end_flash(self) -> None:
        shown = self._shown.update(lambda shown: replace(shown, flash=None))
        if shown.steady is not None:
            self._show(*shown.steady, self._ink)
        else:
            self._window.hide()
