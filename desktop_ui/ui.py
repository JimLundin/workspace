"""Qt owns the desktop's main thread; callers enqueue work or await explicit input.

The views show what dictation and meetings report (the voice, jobs and recording).
No GUI objects cross the keyboard process.
"""

import queue
import threading
import traceback
from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass, field, replace
from typing import Protocol, assert_never

lazy import shiboken6
lazy from PySide6 import QtCore, QtWidgets

import winapi.shapes
from cell import Cell
from desktop_ui import job_queue
from desktop_ui.bar_events import ChordHeld, DictationShown, JobShown, LayoutShown, OverlayShown, RecordingShown
from desktop_ui.qt_runtime import prepare
from desktop_ui.ui_control import BarBuilt, BarOverlay, Effect, Fact, OverlayPublished, UiState, transition
from winapi.shapes import Rect
lazy from contracts.recording_state import RecordingAction
lazy from desktop_ui.components.appearance import scheme, tokens, tooltip_style
lazy from desktop_ui.desktop_bar import BarActions, DesktopBar
lazy from desktop_ui.dialogs import Job, bring_forward, near_pointer
lazy from desktop_ui.keymap_views import KeymapOverlay, KeymapWindow
lazy from desktop_ui.layer_indicator import Indicator
lazy from desktop_ui.navigation import Order
lazy from desktop_ui.qt_ui import application
lazy from desktop_ui.vector_icons import icon
lazy from desktop_ui.window_switcher import WindowSwitcher
lazy from miryoku.layout import Layer, Scancode
lazy from protocol import Tool

prepare()


class DesktopFactory(Protocol):
    def __call__(self, actions: BarActions, *, audio_level: Callable[[], float | None] | None = None) -> DesktopBar: ...


def _native_desktop(actions: BarActions, *, audio_level: Callable[[], float | None] | None = None) -> DesktopBar:
    # Resolve the lazy native module only when Qt owns this view's construction.
    return DesktopBar.open(actions, audio_level=audio_level)


@dataclass(frozen=True, slots=True)
class Views:
    """How Ui builds its native views; a test builds isolated ones and keeps what it built."""

    desktop: DesktopFactory = _native_desktop


@dataclass(frozen=True, slots=True)
class _Built:
    """The views built so far, on the Qt thread, each made on first use."""

    bar: DesktopBar | None = None
    switcher: WindowSwitcher | None = None
    indicator: Indicator | None = None
    keymap: KeymapWindow | None = None
    overlay: KeymapOverlay | None = None


@dataclass(frozen=True, slots=True)
class _OnQt:
    state: UiState = field(default_factory=UiState)
    built: _Built = field(default_factory=_Built)


@dataclass(frozen=True, slots=True)
class Ui:
    """The desktop's views on the Qt thread, and the fold of what they must replay.

    Any thread posts a job or reports a fact; the Qt thread drains them in order.
    """

    _views: Views
    _on_problem: Callable[[str], None] | None
    _root: QtWidgets.QApplication
    _poll_timer: QtCore.QTimer
    _thread: threading.Thread
    _qt: Cell[_OnQt] = field(default_factory=lambda: Cell(_OnQt()), init=False, repr=False)
    """The fold's state and the views built so far: the Qt thread alone replaces it."""
    _jobs: queue.Queue[Job] = field(default_factory=queue.Queue[Job], init=False, repr=False)
    _draining: threading.Event = field(default_factory=threading.Event, init=False, repr=False)
    """Qt can deliver nested events inside a native job; the queue still runs serially."""
    _closed: threading.Event = field(default_factory=threading.Event, init=False, repr=False)
    _inputs_closed: threading.Event = field(default_factory=threading.Event, init=False, repr=False)

    @classmethod
    def start(cls, *, views: Views | None = None, on_problem: Callable[[str], None] | None = None) -> Ui:
        """Qt on the process's main thread, polling the job queue every 20 ms."""
        if threading.current_thread() is not threading.main_thread():
            raise RuntimeError("Qt must be created on the process's main thread.")
        root = application()
        root.setStyleSheet(tooltip_style(tokens(scheme())))
        timer = QtCore.QTimer(root)
        timer.setInterval(20)
        ui = cls(Views() if views is None else views, on_problem, root, timer, threading.current_thread())
        timer.timeout.connect(ui.drain)
        timer.start()
        return ui

    def run(self) -> None:
        """Run and dispose Qt on the main thread, including binding-owned deletions."""
        if threading.current_thread() is not self._thread:
            raise RuntimeError("Qt must run on the thread that created it.")
        try:
            self._root.exec()
        finally:
            try:
                self._close_inputs()
                try:
                    self.close_views()
                finally:
                    self._poll_timer.stop()
                    for window in self._root.topLevelWidgets():
                        window.hide()
                        window.deleteLater()
                    QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
                    icon.cache_clear()
                    shiboken6.delete(self._root)
            finally:
                self._closed.set()

    @property
    def _built(self) -> _Built:
        return self._qt.get().built

    def _set_built(self, built: _Built) -> None:
        self._qt.set(replace(self._qt.get(), built=built))

    def close_views(self) -> None:
        """Close every view on the Qt thread."""
        self._poll_timer.stop()
        self.close_desktop()

    def _close_inputs(self) -> None:
        self._inputs_closed.set()

    def _accepting(self) -> bool:
        return not self._inputs_closed.is_set()

    def drain(self) -> None:
        """Run queued jobs for up to a quarter frame; call only on the Qt thread (see `job_queue.drain`)."""
        job_queue.drain(self._jobs, self._run_job, self._draining)

    def _run_job(self, job: Job) -> None:
        try:
            job(self._root)
        except Exception:
            traceback.print_exc()

    def close(self) -> None:
        if self._closed.is_set():
            return
        self._close_inputs()
        self.post(lambda root: root.quit())
        if threading.current_thread() is not self._thread and not self._closed.wait(timeout=5):
            raise OSError("The Qt UI did not finish closing.")

    def post(self, job: Job) -> None:
        """Runs a job on the Qt thread, soon; doesn't wait."""
        if not self._closed.is_set():
            self._jobs.put(job)

    def settled(self) -> bool:
        """Whether no job is waiting for the Qt thread."""
        return self._jobs.empty()

    def problem(self, message: str) -> None:
        if self._on_problem is not None:
            self._on_problem(message)

    # ---- the fold ----------------------------------------------------------------------

    def report(self, fact: Fact) -> None:
        """Any thread: fold `fact` on the Qt thread, in order with the other jobs."""
        self.post(lambda _: self._fold(fact))

    def _fold(self, fact: Fact) -> None:
        state, effects = transition(self._qt.get().state, fact)
        self._qt.set(replace(self._qt.get(), state=state))
        for effect in effects:
            self._perform(effect)

    @property
    def _bar(self) -> DesktopBar | None:
        return self._built.bar

    def _perform(self, effect: Effect) -> None:
        match effect:
            case BarOverlay(enabled):
                if (bar := self._bar) is not None:
                    bar.handle(OverlayShown(enabled))
            case _:
                assert_never(effect)

    # ---- what dictation and meetings do ------------------------------------------------

    def show_activity(self, change: DictationShown | JobShown | RecordingShown) -> None:
        """Any thread: the bar shows what dictation or a meeting is doing."""
        self._with_bar(lambda bar: bar.handle(change))

    def desktop_overlay(self, *, enabled: bool) -> None:
        self.report(OverlayPublished(enabled))

    # ---- the key map and the layer indicator ------------------------------------------

    def show_keymap(self) -> None:
        def job(root: QtWidgets.QApplication) -> None:
            built = self._built
            if built.keymap is None or not shiboken6.isValid(built.keymap.window):
                self._set_built(replace(built, keymap=KeymapWindow.open(root)))
            else:
                bring_forward(built.keymap.window, built.keymap.canvas)

        self.post(job)

    def show_keyboard_overlay(
        self,
        layer: Layer | None,
        title: str,
        work: Rect,
        *,
        visible: bool,
        pressed: frozenset[Scancode] = frozenset(),
    ) -> None:
        """A faded key map that follows the current layer without taking keyboard focus."""

        def job(root: QtWidgets.QApplication) -> None:
            overlay = self._built.overlay
            if overlay is None:
                if not visible:
                    return
                overlay = KeymapOverlay.open(root)
                self._set_built(replace(self._built, overlay=overlay))
            overlay.show(layer, title, work, visible=visible, pressed=pressed)

        self.post(job)

    def show_pressed_keys(self, pressed: frozenset[Scancode], *, reset: bool = False) -> None:
        """Update feedback on the Qt thread without opening a hidden overlay."""

        def job(_: QtWidgets.QApplication) -> None:
            if (overlay := self._built.overlay) is not None:
                overlay.set_pressed(pressed, reset=reset)

        self.post(job)

    def _indicator(self, root: QtWidgets.QApplication) -> Indicator:
        if (indicator := self._built.indicator) is None:
            indicator = Indicator.build(root)
            self._set_built(replace(self._built, indicator=indicator))
        return indicator

    def indicate(self, text: str | None, work: Rect) -> None:
        """What the layer indicator shows from now on (None: nothing), at the bottom of `work`."""
        self.post(lambda root: self._indicator(root).set(text, work))

    def flash(self, text: str, work: Rect, seconds: float = 1.2) -> None:
        """Shows a message in the indicator for a moment."""
        self.post(lambda root: self._indicator(root).flash(text, work, seconds))

    # ---- the bar -----------------------------------------------------------------------

    # Recording, overlay and menu dispatch remain distinct effect ports; audio
    # observation and tool dispatch complete bar composition.
    def desktop(
        self,
        *,
        record: Callable[[RecordingAction], None],
        overlay: Callable[[], None],
        menu: Callable[[], None],
        audio_level: Callable[[], float | None] | None = None,
        tool: Callable[[Tool], None] | None = None,
    ) -> None:
        """Create only Workspace's floating native controls."""

        def create(_: QtWidgets.QApplication) -> None:
            if not self._accepting() or self._bar is not None:
                return
            try:
                actions = BarActions(record, self.show_keymap, overlay, menu, self.problem, tool or (lambda _tool: None))
                self._set_built(replace(self._built, bar=self._views.desktop(actions, audio_level=audio_level)))
                self._fold(BarBuilt())
            except Exception:
                traceback.print_exc()
                self.problem("The Workspace bar could not start. The tray remains available.")

        self.post(create)

    def _with_bar(self, use: Callable[[DesktopBar], None]) -> None:
        def job(_: QtWidgets.QApplication) -> None:
            if (bar := self._bar) is not None:
                use(bar)

        self.post(job)

    def desktop_layout(self, *, enabled: bool) -> None:
        self._with_bar(lambda bar: bar.handle(LayoutShown(enabled)))

    def desktop_chord(self, *, held: bool) -> None:
        self._with_bar(lambda bar: bar.handle(ChordHeld(held)))

    def navigate(self, order: Order) -> None:
        self._with_bar(lambda bar: bar.navigate(order))

    def toggle_taskbar(self) -> None:
        self._with_bar(lambda bar: bar.toggle_taskbar())

    def switch_windows(self, choices: tuple[winapi.shapes.Window, ...], focus: Callable[[int], None]) -> None:
        def show(_: QtWidgets.QApplication) -> None:
            built = self._built
            if built.switcher is not None and built.switcher.isVisible():
                built.switcher.activate()
                return
            current = WindowSwitcher(choices, focus)
            self._set_built(replace(built, switcher=current))

            def cleared(_: int) -> None:
                if self._built.switcher is current:
                    self._set_built(replace(self._built, switcher=None))

            current.finished.connect(cleared)
            near_pointer(current, current.width(), current.height())
            bring_forward(current, current.search)

        self.post(show)

    def close_desktop(self) -> None:
        if self._closed.is_set():
            return
        closed: Future[None] = Future()

        def close(_: QtWidgets.QApplication) -> None:
            try:
                if (bar := self._bar) is not None:
                    bar.close()
                    self._set_built(replace(self._built, bar=None))
            except Exception as error:
                closed.set_exception(OSError(str(error)))
            else:
                closed.set_result(None)

        if threading.current_thread() is self._thread:
            close(self._root)
        else:
            self.post(close)
        try:
            closed.result(timeout=10)
        except TimeoutError:
            raise OSError("The Workspace bar did not finish closing.") from None
