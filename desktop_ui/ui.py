"""Qt owns the desktop's main thread; callers enqueue work or await explicit input.

The desktop shows what the assistant publishes (its session, work and canvas)
and sends the assistant commands through an `AssistantPort`; nothing of the
assistant runs here. No GUI objects cross the keyboard process.
"""

import queue
import threading
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Protocol, assert_never

lazy import shiboken6
lazy from PySide6 import QtCore, QtGui, QtWidgets

import winapi.shapes
from cell import Cell
from contracts.canvas_activity import CanvasRequest
from contracts.desktop_link import (
    AnswerCanvas,
    CanvasNoticed,
    CanvasStatus,
    JobChanged,
    MeetingPage,
    NoticesObserved,
    OpenReference,
    RecordingChanged,
    ReplyFailed,
    RouteSpeech,
    RunRefused,
    SelectAttention,
    ShowWork,
    SpeakToAgent,
    ToDesktop,
    VoiceChanged,
    WorkChanged,
    WorkCommand,
    WorkShown,
)
from contracts.task import TextAnswer
from desktop_ui.qt_runtime import prepare
from desktop_ui.ui_control import (
    BarAutomatic,
    BarBuilt,
    BarDictation,
    BarOverlay,
    BarSession,
    CanvasVoice,
    Effect,
    Fact,
    InboxOpened,
    OverlayPublished,
    PublishCanvas,
    Published,
    Route,
    ShowInbox,
    ToView,
    UiState,
    ViewMessage,
    transition,
)
from winapi.shapes import Rect
lazy import contracts.desktop_attention
lazy import winapi.system_notices
lazy from contracts.card_actions import OpenCanvas
lazy from contracts.recording_state import RecordingAction
lazy from contracts.status import State
lazy from contracts.work_canvas_contracts import CanvasEdits, CanvasPublication
lazy from contracts.work_commands import WorkViewCommand
lazy from desktop_ui import island_agent
lazy from desktop_ui.agent_progress import phases
lazy from desktop_ui.assistant_port import UNAVAILABLE, AssistantPort, RemoteCanvas
lazy from desktop_ui.components.appearance import scheme, tokens, tooltip_style
lazy from desktop_ui.desktop_bar import BarActions, DesktopBar
lazy from desktop_ui.dialogs import Job, bring_forward, near_pointer
lazy from desktop_ui.keymap_views import KeymapOverlay, KeymapWindow
lazy from desktop_ui.layer_indicator import Indicator
lazy from desktop_ui.navigation import Order
lazy from desktop_ui.qt_ui import application
lazy from desktop_ui.request_panel import RequestActions
lazy from desktop_ui.vector_icons import icon
lazy from desktop_ui.window_switcher import WindowSwitcher
lazy from desktop_ui.work_canvas_window import CanvasWindow
lazy from desktop_ui.work_window import WorkWindow
lazy from miryoku.layout import Layer, Scancode
lazy from protocol import Tool

prepare()


class DesktopFactory(Protocol):
    def __call__(self, actions: BarActions, *, audio_level: Callable[[], float | None] | None = None) -> DesktopBar: ...


def _native_desktop(actions: BarActions, *, audio_level: Callable[[], float | None] | None = None) -> DesktopBar:
    # Resolve the lazy native module only when Qt owns this view's construction.
    return DesktopBar.open(actions, audio_level=audio_level)


def _native_canvas_view(root: QtWidgets.QApplication, work: WorkWindow, canvas: CanvasEdits) -> CanvasWindow:
    return CanvasWindow(root, work, canvas)


@dataclass(frozen=True, slots=True)
class Views:
    """How Ui builds its native views; a test builds isolated ones and keeps what it built."""

    desktop: DesktopFactory = _native_desktop
    canvas: Callable[[QtWidgets.QApplication, WorkWindow, CanvasEdits], CanvasWindow] = _native_canvas_view


@dataclass(frozen=True, slots=True)
class WaitCursor:
    """The standard wait cursor from the canvas's first reveal until its first paint."""

    root: QtWidgets.QApplication

    def show(self) -> None:
        self.root.setOverrideCursor(QtGui.QCursor(QtCore.Qt.CursorShape.WaitCursor))

    def close(self) -> None:
        self.root.restoreOverrideCursor()


@dataclass(frozen=True, slots=True)
class _Built:
    """The views built so far, on the Qt thread, each made on first use."""

    bar: DesktopBar | None = None
    canvas: CanvasWindow | None = None
    switcher: WindowSwitcher | None = None
    indicator: Indicator | None = None
    keymap: KeymapWindow | None = None
    overlay: KeymapOverlay | None = None


@dataclass(frozen=True, slots=True)
class Ui:
    """The desktop's views on the Qt thread, and the fold of what the assistant publishes into them.

    Any thread posts a job or reports a fact; the Qt thread drains them in order.
    Ui owns the desktop's views; the assistant is reached only through its port.
    """

    _views: Views
    _assistant: AssistantPort
    _on_problem: Callable[[str], None] | None
    _root: QtWidgets.QApplication
    _poll_timer: QtCore.QTimer
    _thread: threading.Thread
    _canvas: RemoteCanvas
    _state: Cell[UiState] = field(default_factory=lambda: Cell(UiState()), init=False, repr=False)
    _built: Cell[_Built] = field(default_factory=lambda: Cell(_Built()), init=False, repr=False)
    """Replaced on the Qt thread as views are built and closed."""
    _work: Cell[WorkWindow | None] = field(default_factory=lambda: Cell[WorkWindow | None](None), init=False, repr=False)
    """The work controller, made on first use from any thread under `_work_lock`."""
    _work_lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _jobs: queue.Queue[Job] = field(default_factory=queue.Queue[Job], init=False, repr=False)
    _draining: Cell[bool] = field(default_factory=lambda: Cell(False), init=False, repr=False)
    """Qt can deliver nested events inside a native job; the queue still runs serially."""
    _closed: threading.Event = field(default_factory=threading.Event, init=False, repr=False)
    _inputs_closed: Cell[bool] = field(default_factory=lambda: Cell(False), init=False, repr=False)
    _input_lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    @classmethod
    def start(cls, assistant: AssistantPort, *, views: Views | None = None, on_problem: Callable[[str], None] | None = None) -> Ui:
        """Qt on the process's main thread, polling the job queue every 20 ms."""
        if threading.current_thread() is not threading.main_thread():
            raise RuntimeError("Qt must be created on the process's main thread.")
        root = application()
        root.setStyleSheet(tooltip_style(tokens(scheme())))
        timer = QtCore.QTimer(root)
        timer.setInterval(20)
        ui = cls(Views() if views is None else views, assistant, on_problem, root, timer, threading.current_thread(), RemoteCanvas(assistant))
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

    def close_views(self) -> None:
        """Close every view on the Qt thread, running queued jobs until each acknowledges."""
        self._poll_timer.stop()
        try:
            self.close_desktop()
        finally:
            self.close_windows()
            self._built.set(replace(self._built.get(), canvas=None))
            while (work := self._work.get()) is not None and not work.publication.closed_ready.is_set():
                self.drain()

    def _close_inputs(self) -> None:
        with self._input_lock:
            self._inputs_closed.set(True)

    def _accepting(self) -> bool:
        with self._input_lock:
            return not self._inputs_closed.get()

    def drain(self) -> None:
        """Yield after 4 ms of queued work; call only on the Qt thread.

        A quarter of a 60 Hz frame leaves room for painting and input. One job
        still runs to completion; expensive preparation belongs off this queue.
        """
        if self._draining.get():
            return
        self._draining.set(True)
        deadline = time.monotonic() + 0.004
        try:
            for _ in range(64):
                try:
                    job = self._jobs.get_nowait()
                except queue.Empty:
                    break
                try:
                    job(self._root)
                except Exception:
                    traceback.print_exc()
                if time.monotonic() >= deadline:
                    break
        finally:
            self._draining.set(False)

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
        state, effects = transition(self._state.get(), fact)
        self._state.set(state)
        for effect in effects:
            self._perform(effect)

    @property
    def _bar(self) -> DesktopBar | None:
        return self._built.get().bar

    @property
    def _canvas_view(self) -> CanvasWindow | None:
        return self._built.get().canvas

    def _perform(self, effect: Effect) -> None:
        match effect:
            case BarSession(session):
                if (bar := self._bar) is not None:
                    bar.agent_changed(island_agent.activity(session))
                    bar.requests_changed(tuple(phases(session)))
                    bar.notices_changed(island_agent.notices(session))
            case BarDictation(active):
                if (bar := self._bar) is not None:
                    bar.dictation(active=active)
            case CanvasVoice(pressed):
                if (view := self._canvas_view) is not None:
                    view.voice_pressed(pressed=pressed)
            case BarAutomatic(status):
                if (bar := self._bar) is not None:
                    bar.automatic_changed(status)
            case BarOverlay(enabled):
                if (bar := self._bar) is not None:
                    bar.overlay_changed(enabled=enabled)
            case PublishCanvas(publication, replay=replay):
                self._publish_canvas(publication, replay=replay)
            case ShowInbox(asked):
                if self._accepting() and ((bar := self._bar) is None or not bar.open_inbox(asked)):
                    self.show_canvas()
            case Route(text, question):
                self._route(text, question)
            case ToView(message):
                self._to_view(message)
            case _:
                assert_never(effect)

    def _publish_canvas(self, publication: CanvasPublication, *, replay: bool) -> None:
        """Every view takes the publication; a replay to a late-built view repeats no notice."""
        self._canvas.published(publication)
        if (bar := self._bar) is not None:
            bar.inbox_changed(len(publication.waiting))
        view = self._canvas_view
        if view is not None:
            view.show_document(publication.document)
        if not replay:
            notice = contracts.desktop_attention.interrupts(publication.notice, view.focus() if view is not None else None)
            if notice is not None:
                self._assistant.send(CanvasNoticed(notice.title, notice.target))

    def _route(self, text: str, question: CanvasRequest | None) -> None:
        """A waiting question takes spoken words first, then the canvas's instruction, then the conversation.

        A rejected clarification reply is consumed here, so it cannot accidentally
        answer another question or become a new task. Dictation has its own path.
        """
        if question is not None:
            self.answer_canvas(question, text)
            return
        view = self._canvas_view
        target = contracts.desktop_attention.speech_target(self._canvas.waiting(), view.focus() if view is not None else None)
        match target:
            case contracts.desktop_attention.AnswerQuestion(request=request):
                if not self.answer_canvas(request, text) and view is not None:
                    view.reply_failed()
            case contracts.desktop_attention.Speech.INSTRUCT:
                if view is not None:
                    view.instruct(text)
            case contracts.desktop_attention.Speech.CONVERSATION:
                if not self._assistant.send(SpeakToAgent(text)):
                    self.problem(UNAVAILABLE)
            case _:
                assert_never(target)

    def _to_view(self, message: ViewMessage) -> None:
        bar, view = self._bar, self._canvas_view
        match message:
            case JobChanged(job=job):
                if bar is not None:
                    bar.job_changed(job)
            case RecordingChanged(recording=recording):
                if bar is not None:
                    bar.recording_changed(recording)
            case WorkChanged(snapshot=snapshot):
                self._canvas.catalog_changed(snapshot.personal.catalog)
                self.work_window().publish(snapshot)
            case ShowWork():
                self.work_window().show()
            case OpenReference(url=url):
                if not QtGui.QDesktopServices.openUrl(QtCore.QUrl(url)):
                    self.problem("The original reference could not be opened.")
            case ReplyFailed():
                if view is not None:
                    view.reply_failed()
            case MeetingPage(transcript_path=path, page=page):
                if view is not None:
                    view.meeting_page(path, page)
            case CanvasStatus(text=text):
                if view is not None:
                    view.canvas_status(text)
            case RunRefused(run=run, reason=reason):
                if view is not None:
                    view.run_refused(run, reason)
            case _:
                assert_never(message)

    # ---- what the assistant publishes --------------------------------------------------

    def show(self, message: ToDesktop) -> None:
        """Any thread: show what the assistant published."""
        self.report(Published(message))

    def desktop_state(self, state: State, *, agent_speaking: bool = False) -> None:
        self.show(VoiceChanged(state, agent_speaking=agent_speaking))

    def route_speech(self, text: str) -> None:
        self.show(RouteSpeech(text))

    def desktop_overlay(self, *, enabled: bool) -> None:
        self.report(OverlayPublished(enabled))

    def open_inbox(self) -> None:
        self.report(InboxOpened())

    def system_notices(self, observation: winapi.system_notices.Observed) -> None:
        """Windows notifications the bar observed go to the assistant's inbox triage."""
        self._assistant.send(NoticesObserved(observation))

    # ---- the key map and the layer indicator ------------------------------------------

    def show_keymap(self) -> None:
        def job(root: QtWidgets.QApplication) -> None:
            built = self._built.get()
            if built.keymap is None or not shiboken6.isValid(built.keymap.window):
                self._built.set(replace(built, keymap=KeymapWindow(root)))
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
            overlay = self._built.get().overlay
            if overlay is None:
                if not visible:
                    return
                overlay = KeymapOverlay(root)
                self._built.set(replace(self._built.get(), overlay=overlay))
            overlay.show(layer, title, work, visible=visible, pressed=pressed)

        self.post(job)

    def show_pressed_keys(self, pressed: frozenset[Scancode], *, reset: bool = False) -> None:
        """Update feedback on the Qt thread without opening a hidden overlay."""

        def job(_: QtWidgets.QApplication) -> None:
            if (overlay := self._built.get().overlay) is not None:
                overlay.set_pressed(pressed, reset=reset)

        self.post(job)

    def _indicator(self, root: QtWidgets.QApplication) -> Indicator:
        if (indicator := self._built.get().indicator) is None:
            indicator = Indicator(root)
            self._built.set(replace(self._built.get(), indicator=indicator))
        return indicator

    def indicate(self, text: str | None, work: Rect) -> None:
        """What the layer indicator shows from now on (None: nothing), at the bottom of `work`."""
        self.post(lambda root: self._indicator(root).set(text, work))

    def flash(self, text: str, work: Rect, seconds: float = 1.2) -> None:
        """Shows a message in the indicator for a moment."""
        self.post(lambda root: self._indicator(root).flash(text, work, seconds))

    # ---- the work window and the canvas ------------------------------------------------

    def close_windows(self) -> None:
        """Close the work window; off the Qt thread, wait briefly for its view to release."""
        if (work := self._work.get()) is None:
            return
        work.close()
        if self._closed.is_set():
            work.publication.abandon()
        elif threading.current_thread() is not self._thread:
            work.publication.closed_ready.wait(timeout=3)

    def _work_command(self, command: WorkViewCommand) -> None:
        if not self._assistant.send(WorkCommand(command)):
            raise OSError(UNAVAILABLE)

    def work_window(self) -> WorkWindow:
        """The work controller; native preparation and showing are explicit."""
        with self._work_lock:
            if (work := self._work.get()) is None:
                root = self._root
                work = WorkWindow(
                    self._work_command,
                    post=lambda job: self.post(lambda _: job()),
                    create_view=self._create_work,
                    on_problem=self.problem,
                    create_loading=lambda: WaitCursor(root),
                )
                self._work.set(work)
            return work

    def _create_work(self, work: WorkWindow) -> CanvasWindow:
        view = self._views.canvas(self._root, work, self._canvas)
        self._built.set(replace(self._built.get(), canvas=view))
        view.voice_pressed(pressed=self._state.get().agent_speaking)
        return view

    def open_canvas_at(self, identity: str) -> None:
        self.show_canvas()

        def reveal(_: QtWidgets.QApplication) -> None:
            if (view := self._canvas_view) is not None:
                view.open_at(identity)

        self.post(reveal)

    def answer_canvas(self, request: CanvasRequest, value: str) -> bool:
        try:
            answer = TextAnswer(value)
        except ValueError:
            return False
        return self._assistant.send(AnswerCanvas(request, answer))

    def show_canvas(self) -> None:
        self.work_window().show()
        self._assistant.send(WorkShown())

    def request_action(self, action: OpenCanvas) -> None:
        if (bar := self._bar) is not None:
            bar.close_menu(restore=False)
        self.open_canvas_at(action.target)

    def select_request(self, request: CanvasRequest | None) -> None:
        self._assistant.send(SelectAttention(request))

    # ---- the bar -----------------------------------------------------------------------

    # View navigation, stop, overlay, menu dispatch and error reporting remain
    # distinct effect ports; audio observation and tool dispatch complete bar composition.
    def desktop(  # noqa: PLR0913 - one callback per window event
        self,
        *,
        record: Callable[[RecordingAction], None],
        stop: Callable[[], None],
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
                actions = BarActions(
                    self.show_canvas,
                    stop,
                    record,
                    self.show_keymap,
                    overlay,
                    menu,
                    self.problem,
                    tool or (lambda _tool: None),
                    self.system_notices,
                    inbox=self.open_inbox,
                    open_item=self.open_canvas_at,
                    requests=RequestActions(self.request_action, self.select_request),
                )
                self._built.set(replace(self._built.get(), bar=self._views.desktop(actions, audio_level=audio_level)))
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
        self._with_bar(lambda bar: bar.layout(enabled=enabled))

    def desktop_chord(self, *, held: bool) -> None:
        self._with_bar(lambda bar: bar.chord(held=held))

    def navigate(self, order: Order) -> None:
        self._with_bar(lambda bar: bar.navigate(order))

    def toggle_taskbar(self) -> None:
        self._with_bar(lambda bar: bar.toggle_taskbar())

    def switch_windows(self, choices: tuple[winapi.shapes.Window, ...], focus: Callable[[int], None]) -> None:
        def show(_: QtWidgets.QApplication) -> None:
            built = self._built.get()
            if built.switcher is not None and built.switcher.isVisible():
                built.switcher.activate()
                return
            current = WindowSwitcher(choices, focus)
            self._built.set(replace(built, switcher=current))

            def cleared(_: int) -> None:
                if self._built.get().switcher is current:
                    self._built.set(replace(self._built.get(), switcher=None))

            current.finished.connect(cleared)
            near_pointer(current, current.width(), current.height())
            bring_forward(current, current.search)

        self.post(show)

    def close_desktop(self) -> None:
        if self._closed.is_set():
            return
        done = threading.Event()
        problem: Cell[str] = Cell("")

        def close(_: QtWidgets.QApplication) -> None:
            try:
                if (bar := self._bar) is not None:
                    bar.close()
                    self._built.set(replace(self._built.get(), bar=None))
            except Exception as error:
                problem.set(str(error))
            finally:
                done.set()

        if threading.current_thread() is self._thread:
            close(self._root)
        else:
            self.post(close)
            if not done.wait(timeout=10):
                raise OSError("The Workspace bar did not finish closing.")
        if problem.get():
            raise OSError(problem.get())
