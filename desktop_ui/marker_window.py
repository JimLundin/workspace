"""Paints the dictation marker beside the caret: the microphone's trace while listening, pulsing dots while
transcribing and typing, then a tick or a cross.

`desktop_ui.dictation_marker` decides what shows and where; this window only
draws it. It is a click-through tool window that never activates, so the app
being dictated into keeps the keyboard. Its timers run only while it shows
something that moves.
"""

import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace
from typing import assert_never, override

lazy from PySide6 import QtCore, QtGui, QtWidgets
lazy from PySide6.QtCore import Qt

from cell import Cell
from desktop_ui.audio_meter import AudioMeter
from desktop_ui.bar_events import BarSpec
from desktop_ui.components.appearance import CanvasBar, Look, Scheme, Shade, look
from desktop_ui.components.meaning import Tint
from desktop_ui.components.text import color
from desktop_ui.components.widgets import device_size, tool_window
from desktop_ui.dictation_marker import Outcome, Shown, Step, placed
from desktop_ui.key_hint_overlay import paint_surface
from desktop_ui.live_marks import Beat, level, paint_dots, paint_wave
from desktop_ui.overlay import nearest_work_area
from desktop_ui.qt_runtime import prepare
from desktop_ui.qt_ui import cancel, later
from desktop_ui.vector_icons import paint_icon
from winapi import appearance, screen, windows
from winapi.caret import Anchor
from winapi.shapes import Point

prepare()

FRAME_MS = 16


@dataclass(frozen=True, slots=True, kw_only=True)
class MarkerSpec:
    """The marker's own choices; its sizes, clocks and glass are the bar's."""

    height: float
    gap: float
    """Between the marker and what it marks."""
    flash: float
    """Seconds an outcome stays before the marker leaves."""
    steps: frozendict[Step, str | None]
    """The symbol before each step's live mark, if any."""
    outcomes: frozendict[Outcome, str]
    scheme: Scheme
    """The marker floats over any window, so it keeps one scheme."""


WAVE = sentinel("WAVE")
DOTS = sentinel("DOTS")


@dataclass(frozen=True, slots=True)
class Symbol:
    name: str
    ink: Shade


type Part = Symbol | WAVE | DOTS


@dataclass(frozen=True, slots=True)
class _Drawn:
    shown: Shown | None = None
    surface: Look | None = None
    contrast: bool = False
    flash: QtCore.QTimer | None = None
    """The timer ending an outcome's flash."""
    samples: tuple[float, ...] = ()
    wave_from: tuple[float, ...] = ()
    sampled_at: float = 0.0


class MarkerWindow(QtWidgets.QWidget):
    """The marker's capsule; what it paints is in its owner's state."""

    __slots__ = ("bar", "drawn", "spec")

    def __init__(self, spec: MarkerSpec, bar: BarSpec, drawn: Cell[_Drawn]) -> None:
        super().__init__()
        tool_window(self, "Workspace dictation", on_top=True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.spec, self.bar, self.drawn = spec, bar, drawn

    def parts(self, shown: Shown, surface: Look, *, contrast: bool) -> tuple[Part, ...]:
        ink = surface.lettering.ink
        match shown:
            case Step.LISTENING:
                lead = Shade(self.bar.palette.microphone) if not contrast else ink
                mark: Part = WAVE
            case Step.TRANSCRIBING | Step.TYPING:
                lead, mark = ink, DOTS
            case Outcome.DONE:
                return (Symbol(self.spec.outcomes[shown], ink),)
            case Outcome.FAILED:
                return (Symbol(self.spec.outcomes[shown], ink if contrast else Shade(self.bar.palette.red)),)
            case _:
                assert_never(shown)
        name = self.spec.steps[shown]
        return (Symbol(name, lead), mark) if name is not None else (mark,)

    def content_width(self, parts: tuple[Part, ...]) -> float:
        """The parts side by side, with the icon's inset at either end so a lone symbol sits in a circle."""
        capsule = self.bar.sizes.capsule
        inner = sum(_part_width(part, self.bar) for part in parts)
        return inner + capsule.part_gap * (len(parts) - 1) + (self.spec.height - capsule.icon)

    @override
    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        drawn = self.drawn.get()
        if drawn.shown is None or drawn.surface is None:
            return
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        paint_surface(painter, QtCore.QRectF(self.rect()), drawn.surface, self.bar.glass)
        sizes, timing = self.bar.sizes, self.bar.timing
        capsule, middle = sizes.capsule, self.spec.height / 2
        x = (self.spec.height - capsule.icon) / 2
        now = time.monotonic()
        ink = drawn.surface.lettering.ink
        for part in self.parts(drawn.shown, drawn.surface, contrast=drawn.contrast):
            match part:
                case Symbol(name, symbol_ink):
                    paint_icon(painter, name, symbol_ink, QtCore.QRectF(x, middle - capsule.icon / 2, capsule.icon, capsule.icon))
                case _ if part is WAVE:
                    painter.setBrush(color(ink))
                    paint_wave(painter, QtCore.QPointF(x, middle), _trace(drawn, now, timing.wave_sample), capsule, sizes.markers)
                case _:
                    beat = Beat(now / timing.pulse % 1, timing.lag, self.bar.washes.resting)
                    paint_dots(painter, QtCore.QRectF(x, middle, capsule.dots, 0), beat, sizes.markers, ink)
            x += _part_width(part, self.bar) + capsule.part_gap
        painter.end()


def _part_width(part: Part, bar: BarSpec) -> float:
    capsule = bar.sizes.capsule
    match part:
        case Symbol():
            return capsule.icon
        case _ if part is WAVE:
            return capsule.wave
        case _:
            return capsule.dots


def _trace(drawn: _Drawn, now: float, every: float) -> Iterator[float]:
    """The trace moving from its previous samples to its latest across one sampling interval."""
    progress = min(1.0, max(0.0, (now - drawn.sampled_at) / every))
    return (before + (after - before) * progress for before, after in zip(drawn.wave_from, drawn.samples, strict=True))


@dataclass(frozen=True, slots=True, weakref_slot=True)
class DictationMarker:
    """Shows what `desktop_ui.dictation_marker` decides; reports when an outcome's flash has ended."""

    spec: MarkerSpec
    bar: BarSpec
    window: MarkerWindow
    frame: int
    meter: AudioMeter
    frames: QtCore.QTimer
    """Repaints while a live mark moves."""
    sampler: QtCore.QTimer
    """Samples the microphone while listening."""
    faded: Callable[[], None]
    drawn: Cell[_Drawn]

    @classmethod
    def build(cls, spec: MarkerSpec, bar: BarSpec, level_of: Callable[[], float | None], faded: Callable[[], None]) -> DictationMarker:
        """`level_of` reads the microphone off the Qt thread; `faded` reports an outcome's flash ending."""
        drawn = Cell(_Drawn())
        window = MarkerWindow(spec, bar, drawn)
        frame = int(window.winId())
        windows.make_overlay(frame)
        frames, sampler = QtCore.QTimer(window), QtCore.QTimer(window)
        frames.setInterval(FRAME_MS)
        sampler.setTimerType(Qt.TimerType.PreciseTimer)
        sampler.setInterval(round(bar.timing.wave_sample * 1000))
        frames.timeout.connect(window.update)
        marker = cls(spec, bar, window, frame, AudioMeter.start(level_of), frames, sampler, faded, drawn)
        sampler.timeout.connect(marker.sample)
        return marker

    def show(self, marked: tuple[Anchor, Shown] | None) -> None:
        if marked is None:
            self._hide()
            return
        anchor, shown = marked
        before = self.drawn.get()
        drawn = self._become(shown, before) if shown != before.shown else before
        if drawn.surface is None:
            return
        parts = self.window.parts(shown, drawn.surface, contrast=drawn.contrast)
        self.window.resize(round(self.window.content_width(parts)), round(self.spec.height))
        ratio = self.window.devicePixelRatioF()
        size = device_size(self.window, ratio)
        centre = Point((anchor.rect.left + anchor.rect.right) // 2, (anchor.rect.top + anchor.rect.bottom) // 2)
        work = nearest_work_area(centre, tuple(monitor.work for monitor in screen.monitors()))
        windows.move(self.frame, placed(anchor, size, work, round(self.spec.gap * ratio)))
        self.window.update()
        if not self.window.isVisible():
            self.window.show()
            windows.show_quietly(self.frame, visible=True)

    def _become(self, shown: Shown, before: _Drawn) -> _Drawn:
        """Start what `shown` needs: the microphone's trace, the frames, an outcome's timer."""
        preference = appearance.preference()
        surface = look(preference, CanvasBar(self.spec.scheme), Tint.NONE, self.bar.glass)
        cancel(before.flash)
        flash = later(self.window, round(self.spec.flash * 1000), self.faded) if isinstance(shown, Outcome) else None
        listening = shown is Step.LISTENING
        # A capture starts its trace silent; the steps after it keep the last trace.
        silent = (0.0,) * self.bar.sizes.capsule.wave_bars
        drawn = replace(
            before,
            shown=shown,
            surface=surface,
            contrast=isinstance(preference, appearance.Contrast),
            flash=flash,
            samples=silent if listening else before.samples,
            wave_from=silent if listening else before.wave_from,
        )
        self.drawn.set(drawn)
        self.meter.listen(enabled=listening)
        _run(self.sampler, running=listening)
        _run(self.frames, running=not isinstance(shown, Outcome))
        return drawn

    def sample(self) -> None:
        """The microphone's latest level enters the trace, which moves to it over the next interval."""
        reading = level(self.meter.level())
        self.drawn.update(lambda drawn: replace(drawn, wave_from=drawn.samples, samples=(*drawn.samples[1:], reading), sampled_at=time.monotonic()))

    def _hide(self) -> None:
        drawn = self.drawn.get()
        cancel(drawn.flash)
        self.drawn.set(_Drawn())
        self.meter.listen(enabled=False)
        _run(self.sampler, running=False)
        _run(self.frames, running=False)
        self.window.hide()

    def close(self) -> None:
        self._hide()
        self.meter.close()
        self.window.close()
        self.window.deleteLater()


def _run(timer: QtCore.QTimer, *, running: bool) -> None:
    if running and not timer.isActive():
        timer.start()
    elif not running and timer.isActive():
        timer.stop()
