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
from dataclasses import dataclass
from typing import Protocol, assert_never

lazy import shiboken6
lazy from PySide6 import QtCore, QtGui, QtWidgets

import winapi.shapes
from contracts.canvas_activity import CanvasRequest
from contracts.desktop_link import (
    AnswerCanvas,
    AutomaticChanged,
    CanvasChanged,
    CanvasNoticed,
    CanvasStatus,
    JobChanged,
    MeetingPage,
    MicLevel,
    NoticesObserved,
    Notify,
    OpenReference,
    RecordingChanged,
    ReplyFailed,
    RouteSpeech,
    RunRefused,
    SelectAttention,
    SessionChanged,
    ShowWork,
    SpeakToAgent,
    ToDesktop,
    VoiceChanged,
    WorkChanged,
    WorkCommand,
    WorkShown,
)
from contracts.feed_origin import FeedRequest
from contracts.task import TextAnswer
from desktop_ui.qt_runtime import prepare
from winapi.shapes import Rect
lazy import contracts.desktop_attention
lazy import contracts.status
lazy import winapi.system_notices
lazy from contracts.agent_session import ChatMessage, Session, Snapshot, notice_text
lazy from contracts.attention import selected_question
lazy from contracts.card_actions import OpenCanvas
lazy from contracts.meeting_detection import AutomaticStatus
lazy from contracts.meetings import MeetingConversation
lazy from contracts.recording_state import RecordingAction, RecordingState
lazy from contracts.status import State
lazy from contracts.work_canvas_contracts import CanvasEdits, CanvasPublication
lazy from contracts.work_commands import WorkViewCommand
lazy from contracts.work_snapshot import WorkSnapshot
lazy from desktop_ui import island_agent
lazy from desktop_ui.agent_progress import Phase, canvas_phases, hint, phases
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
    return DesktopBar(actions, audio_level=audio_level)


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


class Ui:
    __slots__ = (
        "_agent_speaking",
        "_assistant",
        "_automatic_recording",
        "_canvas",
        "_canvas_published",
        "_closed",
        "_desktop",
        "_draining",
        "_indicator",
        "_input_lock",
        "_inputs_closed",
        "_jobs",
        "_keyboard_overlay",
        "_keymap",
        "_on_problem",
        "_overlay_enabled",
        "_poll_timer",
        "_root",
        "_session",
        "_switcher",
        "_thread",
        "_views",
        "_work",
        "_work_lock",
        "_work_view",
    )

    def __init__(self, assistant: AssistantPort, *, views: Views | None = None, on_problem: Callable[[str], None] | None = None) -> None:
        # Ui owns the desktop's views; the assistant is reached only through its port.
        self._views: Views = Views() if views is None else views
        if threading.current_thread() is not threading.main_thread():
            raise RuntimeError("Qt must be created on the process's main thread.")
        self._assistant = assistant
        self._on_problem = on_problem
        # Qt owns the latest capture observation, including before the canvas
        # exists, so opening it during a held speech key starts in that state.
        self._agent_speaking: bool = False
        self._session: Snapshot = Session()
        """The assistant's latest agent session, as published."""
        self._desktop: DesktopBar | None = None
        self._automatic_recording = AutomaticStatus.OFF
        self._overlay_enabled = False
        self._switcher: WindowSwitcher | None = None
        self._work: WorkWindow | None = None
        self._work_view: CanvasWindow | None = None
        self._canvas = RemoteCanvas(assistant)
        self._canvas_published: CanvasPublication | None = None
        self._work_lock = threading.Lock()
        self._indicator: Indicator | None = None
        """Made on first use, on the Qt thread."""
        self._keymap: KeymapWindow | None = None
        self._keyboard_overlay: KeymapOverlay | None = None
        self._jobs: queue.Queue[Job] = queue.Queue()
        # Qt can deliver nested events inside a native job. This owner keeps
        # queue execution serial, including across those nested deliveries.
        self._draining = False
        self._closed, self._inputs_closed = threading.Event(), False
        self._input_lock = threading.Lock()
        self._thread = threading.current_thread()
        self._root = application()
        self._root.setStyleSheet(tooltip_style(tokens(scheme())))
        self._poll_timer = QtCore.QTimer(self._root)
        self._poll_timer.setInterval(20)
        self._poll_timer.timeout.connect(self.drain)
        self._poll_timer.start()

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
            self._work_view = None
            while self._work is not None and not self._work.publication.closed_ready.is_set():
                self.drain()

    def _close_inputs(self) -> None:
        with self._input_lock:
            self._inputs_closed = True

    def drain(self) -> None:
        """Yield after 4 ms of queued work; call only on the Qt thread.

        A quarter of a 60 Hz frame leaves room for painting and input. One job
        still runs to completion; expensive preparation belongs off this queue.
        """
        if self._draining:
            return
        self._draining = True
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
            self._draining = False

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

    def problem(self, message: str) -> None:
        if self._on_problem is not None:
            self._on_problem(message)

    # ---- the key map and the layer indicator ------------------------------------------

    def show_keymap(self) -> None:
        def job(root: QtWidgets.QApplication) -> None:
            if self._keymap is None or not shiboken6.isValid(self._keymap.window):
                self._keymap = KeymapWindow(root)
            else:
                bring_forward(self._keymap.window, self._keymap.canvas)

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
            if self._keyboard_overlay is None:
                if not visible:
                    return
                self._keyboard_overlay = KeymapOverlay(root)
            self._keyboard_overlay.show(layer, title, work, visible=visible, pressed=pressed)

        self.post(job)

    def show_pressed_keys(self, pressed: frozenset[Scancode], *, reset: bool = False) -> None:
        """Update feedback on the Qt thread without opening a hidden overlay."""

        def job(root: QtWidgets.QApplication) -> None:
            if self._keyboard_overlay is not None:
                self._keyboard_overlay.set_pressed(pressed, reset=reset)

        self.post(job)

    def _overlay(self, root: QtWidgets.QApplication) -> Indicator:
        if self._indicator is None:
            self._indicator = Indicator(root)
        return self._indicator

    def indicate(self, text: str | None, work: Rect) -> None:
        """What the layer indicator shows from now on (None: nothing), at the bottom of `work`."""
        self.post(lambda root: self._overlay(root).set(text, work))

    def flash(self, text: str, work: Rect, seconds: float = 1.2) -> None:
        """Shows a message in the indicator for a moment."""
        self.post(lambda root: self._overlay(root).flash(text, work, seconds))

    # ---- what the assistant publishes --------------------------------------------------

    def show(self, message: ToDesktop) -> None:
        """Any thread: show what the assistant published. The tray's notices and the
        microphone's level belong to the desktop's owner, which reads them first."""
        match message:
            case SessionChanged(session=session):
                self.session_changed(session)
            case WorkChanged(snapshot=snapshot):
                self.work_changed(snapshot)
            case CanvasChanged(publication=publication):
                self.publish_canvas(publication)
            case VoiceChanged(state=state, agent_speaking=speaking):
                self.desktop_state(state, agent_speaking=speaking)
            case JobChanged(job=job):
                self.desktop_job(job)
            case RecordingChanged(recording=recording):
                self.desktop_recording(recording)
            case AutomaticChanged(status=status):
                self.desktop_automatic(status)
            case ShowWork():
                self.work_window().show()
            case RouteSpeech(text=text):
                self.route_speech(text)
            case OpenReference(url=url):
                self.open_reference(url)
            case ReplyFailed():
                self.reply_failed()
            case MeetingPage(transcript_path=path, page=page):
                self.meeting_page(path, page)
            case CanvasStatus(text=text):
                self.post(lambda _: self._work_view.canvas_status(text) if self._work_view is not None else None)
            case RunRefused(run=run, reason=reason):
                self.post(lambda _: self._work_view.run_refused(run, reason) if self._work_view is not None else None)
            case MicLevel() | Notify():
                pass
            case _:
                assert_never(message)

    def session_changed(self, session: Snapshot) -> None:
        """The assistant's agent session: the bar, inbox and canvas show it."""

        def publish(_: QtWidgets.QApplication) -> None:
            self._session = session
            self.refresh_inbox()

        self.post(publish)

    def work_changed(self, snapshot: WorkSnapshot) -> None:
        self._canvas.catalog_changed(snapshot.personal.catalog)
        self.work_window().publish(snapshot)

    def system_notices(self, observation: winapi.system_notices.Observed) -> None:
        """Windows notifications the bar observed go to the assistant's inbox triage."""
        self._assistant.send(NoticesObserved(observation))

    def refresh_inbox(self) -> None:
        """Publish attention on the Qt thread, including before the bar exists."""
        if self._desktop is not None:
            self._desktop.agent_changed(island_agent.activity(self._session))
            self._desktop.requests_changed(tuple(phases(self._session)))
            self._desktop.notices_changed(island_agent.notices(self._session))

    def close_windows(self) -> None:
        """Close the work window; off the Qt thread, wait briefly for its view to release."""
        if self._work is None:
            return
        self._work.close()
        if self._closed.is_set():
            self._work.publication.abandon()
        elif threading.current_thread() is not self._thread:
            self._work.publication.closed_ready.wait(timeout=3)

    def _work_command(self, command: WorkViewCommand) -> None:
        if not self._assistant.send(WorkCommand(command)):
            raise OSError(UNAVAILABLE)

    def work_window(self) -> WorkWindow:
        """The work controller; native preparation and showing are explicit."""
        with self._work_lock:
            if self._work is None:
                self._work = WorkWindow(
                    self._work_command,
                    post=lambda job: self.post(lambda root: job()),
                    create_view=self._create_work,
                    on_problem=self.problem,
                    create_loading=lambda: WaitCursor(self._root),
                )
            return self._work

    def _create_work(self, work: WorkWindow) -> CanvasWindow:
        self._work_view = self._views.canvas(self._root, work, self._canvas)
        self._work_view.voice_pressed(pressed=self._agent_speaking)
        return self._work_view

    def publish_canvas(self, publication: CanvasPublication) -> None:
        """Defer owner publications until callers have finished their gesture or command."""
        self.post(lambda _: self._publish_canvas(publication))

    def _publish_canvas(self, publication: CanvasPublication, *, replay: bool = False) -> None:
        """Replay attention to late-created views without repeating the original notice."""
        self._canvas_published = publication
        self._canvas.published(publication)
        if self._desktop is not None:
            self._desktop.inbox_changed(len(publication.waiting))
        if self._work_view is not None:
            self._work_view.show_document(publication.document)
        if not replay:
            focus = self._work_view.focus() if self._work_view is not None else None
            notice = contracts.desktop_attention.interrupts(publication.notice, focus)
            if notice is not None:
                self._assistant.send(CanvasNoticed(notice.title, notice.target))

    def open_canvas_at(self, identity: str) -> None:
        self.show_canvas()

        def reveal(_: QtWidgets.QApplication) -> None:
            if self._work_view is not None:
                self._work_view.open_at(identity)

        self.post(reveal)

    def open_reference(self, url: str) -> None:
        """Qt delegates a validated original document/page to the desktop shell."""

        def open_original(_: QtWidgets.QApplication) -> None:
            if not QtGui.QDesktopServices.openUrl(QtCore.QUrl(url)):
                self.problem("The original reference could not be opened.")

        self.post(open_original)

    def meeting_page(self, transcript_path: str, page: MeetingConversation | None) -> None:
        self.post(lambda _: self._work_view.meeting_page(transcript_path, page) if self._work_view is not None else None)

    def reply_failed(self) -> None:
        self.post(lambda _: self._work_view.reply_failed() if self._work_view is not None else None)

    def route_speech(self, text: str) -> None:
        """Route speech on Qt to a waiting question, the canvas's instruction or the conversation.

        A rejected clarification reply is consumed here, so it cannot accidentally
        answer another question or become a new task. Dictation has its own path.
        """

        def route(_: QtWidgets.QApplication) -> None:
            question = selected_question(self._session.attention, self._session.selected_request)
            if question is not None:
                self.answer_canvas(question.request, text)
                return
            view = self._work_view
            focus = view.focus() if view is not None else None
            target = contracts.desktop_attention.speech_target(self._canvas.waiting(), focus)
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

        self.post(route)

    def answer_canvas(self, request: CanvasRequest, value: str) -> bool:
        try:
            answer = TextAnswer(value)
        except ValueError:
            return False
        return self._assistant.send(AnswerCanvas(request, answer))

    def open_inbox(self) -> None:
        """The bell and the inbox key list waiting questions with the agent's recent news; with neither, the canvas opens."""

        def reveal(_: QtWidgets.QApplication) -> None:
            with self._input_lock:
                if self._inputs_closed:
                    return
            if self._desktop is None or not self._desktop.open_inbox(self.questions()):
                self.show_canvas()

        self.post(reveal)

    def questions(self) -> tuple[Phase, ...]:
        """The session's own waiting questions, then the canvas's others as previews of their context."""
        asked = tuple(phase for phase in phases(self._session) if hint(phase.turn))
        published = self._canvas_published
        if published is None:
            return asked
        routes = frozenset(phase.request for phase in asked)
        preview = Session(
            attention=published.attention,
            messages=tuple(
                ChatMessage(
                    "Workspace", notice_text(question.title, question.id), question.created_at, FeedRequest("canvas:" + question.id, question.title)
                )
                for question in published.waiting
                if question.request not in routes
            ),
        )
        return (*asked, *canvas_phases(preview))

    def show_canvas(self) -> None:
        self.work_window().show()
        self._assistant.send(WorkShown())

    def request_action(self, action: OpenCanvas) -> None:
        if self._desktop is not None:
            self._desktop.close_menu(restore=False)
        self.open_canvas_at(action.target)

    def select_request(self, request: CanvasRequest | None) -> None:
        self._assistant.send(SelectAttention(request))

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

        def create(root: QtWidgets.QApplication) -> None:
            with self._input_lock:
                if self._inputs_closed:
                    return
            if self._desktop is not None:
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
                self._desktop = self._views.desktop(actions, audio_level=audio_level)
                self._desktop.automatic_changed(self._automatic_recording)
                self._desktop.overlay_changed(enabled=self._overlay_enabled)
                if self._canvas_published is not None:
                    self._publish_canvas(self._canvas_published, replay=True)
                self.refresh_inbox()
            except Exception:
                traceback.print_exc()
                self.problem("The Workspace bar could not start. The tray remains available.")

        self.post(create)

    def desktop_state(self, state: State, *, agent_speaking: bool = False) -> None:
        """The tray's state; of it, the bar shows dictation alone: agent work comes from its session."""

        def display(_: QtWidgets.QApplication) -> None:
            self._agent_speaking = agent_speaking
            if self._desktop is not None:
                self._desktop.dictation(active=state is State.LISTENING)
            if self._work_view is not None:
                self._work_view.voice_pressed(pressed=agent_speaking)

        self.post(display)

    def desktop_job(self, job: contracts.status.Job | None) -> None:
        self.post(lambda _: self._desktop.job_changed(job) if self._desktop is not None else None)

    def desktop_recording(self, recording: RecordingState) -> None:
        self.post(lambda _: self._desktop.recording_changed(recording) if self._desktop is not None else None)

    def desktop_automatic(self, status: AutomaticStatus) -> None:
        def display(_: QtWidgets.QApplication) -> None:
            self._automatic_recording = status
            if self._desktop is not None:
                self._desktop.automatic_changed(status)

        self.post(display)

    def desktop_overlay(self, *, enabled: bool) -> None:
        def display(_: QtWidgets.QApplication) -> None:
            self._overlay_enabled = enabled
            if self._desktop is not None:
                self._desktop.overlay_changed(enabled=enabled)

        self.post(display)

    def desktop_layout(self, *, enabled: bool) -> None:
        self.post(lambda _: self._desktop.layout(enabled=enabled) if self._desktop is not None else None)

    def desktop_chord(self, *, held: bool) -> None:
        self.post(lambda _: self._desktop.chord(held=held) if self._desktop is not None else None)

    def navigate(self, order: Order) -> None:
        self.post(lambda _: self._desktop.navigate(order) if self._desktop is not None else None)

    def toggle_taskbar(self) -> None:
        self.post(lambda _: self._desktop.toggle_taskbar() if self._desktop is not None else None)

    def switch_windows(self, choices: tuple[winapi.shapes.Window, ...], focus: Callable[[int], None]) -> None:
        def show(_: QtWidgets.QApplication) -> None:
            if self._switcher is not None and self._switcher.isVisible():
                self._switcher.activate()
                return
            self._switcher = WindowSwitcher(choices, focus)
            current = self._switcher

            def cleared(_: int) -> None:
                if self._switcher is current:
                    self._switcher = None

            current.finished.connect(cleared)
            near_pointer(current, current.width(), current.height())
            bring_forward(current, current.search)

        self.post(show)

    def close_desktop(self) -> None:
        if self._closed.is_set():
            return
        done = threading.Event()
        problems: list[str] = []

        def close(_: QtWidgets.QApplication) -> None:
            try:
                if self._desktop is not None:
                    self._desktop.close()
                    self._desktop = None
            except Exception as error:
                problems.append(str(error))
            finally:
                done.set()

        if threading.current_thread() is self._thread:
            close(self._root)
        else:
            self.post(close)
            if not done.wait(timeout=10):
                raise OSError("The Workspace bar did not finish closing.")
        if problems:
            raise OSError("; ".join(problems))
