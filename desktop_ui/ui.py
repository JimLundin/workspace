"""Qt owns the main thread; callers enqueue work or await explicit input.

No GUI objects cross the keyboard process. Domain work remains off the UI thread.
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
from assistant.canvas_activity import CanvasRequest
from assistant.feed_origin import FeedRequest
from automation.task import TextAnswer
from desktop_ui.qt_runtime import prepare
from winapi.shapes import Rect
lazy import assistant.communications
lazy import desktop_ui.desktop_attention
lazy import winapi.system_notices
lazy from assistant.agent_session import ChatMessage, Session, Snapshot, notice_text
lazy from assistant.attention import selected_question
lazy from assistant.card_actions import OpenCanvas
lazy from assistant.feed_sources import FeedUpdate, NoticesObserved, PendingFeed, TeamsObserved, observe
lazy from assistant.meeting_detection import AutomaticStatus
lazy from assistant.notification_sources import NotificationSources, NotificationState
lazy from assistant.recording_state import RecordingAction, RecordingState
lazy from assistant.state_store import SavedState
lazy from assistant.work_canvas_contracts import CanvasEdits, CanvasPublication
lazy from assistant.work_commands import WorkViewCommand
lazy from desktop_ui import island_agent, island_model
lazy from desktop_ui.agent_progress import Phase, canvas_phases, hint, phases
lazy from desktop_ui.agent_window import AgentWindow
lazy from desktop_ui.components.appearance import scheme, tokens, tooltip_style
lazy from desktop_ui.desktop_bar import BarActions, DesktopBar
lazy from desktop_ui.dialogs import Job, bring_forward, near_pointer
lazy from desktop_ui.icons import State
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


@dataclass(frozen=True, slots=True)
class WorkConnection:
    on_command: Callable[[WorkViewCommand], None]
    on_problem: Callable[[str], None] | None


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


type Assess = Callable[[PendingFeed], None]


@dataclass(frozen=True, slots=True)
class SessionDisplay:
    """The conversation's desktop view: the bar and canvas observe each session, and showing it opens the canvas."""

    publish: Callable[[Snapshot], None]
    reveal: Callable[[], None]

    def render(self, state: Snapshot) -> None:
        self.publish(state)

    def show(self, *, focus: bool = False) -> None:
        self.reveal()

    def close(self) -> None:
        pass


class WaitCursor:
    """The standard wait cursor from the canvas's first reveal until its first paint."""

    def __init__(self, root: QtWidgets.QApplication) -> None:
        self.root: QtWidgets.QApplication = root

    def show(self) -> None:
        self.root.setOverrideCursor(QtGui.QCursor(QtCore.Qt.CursorShape.WaitCursor))

    def close(self) -> None:
        self.root.restoreOverrideCursor()


class Ui:
    __slots__ = (
        "_agent",
        "_agent_lock",
        "_agent_speaking",
        "_agent_waiting",
        "_assess",
        "_automatic_recording",
        "_canvas",
        "_canvas_notice",
        "_canvas_published",
        "_canvas_session",
        "_closed",
        "_desktop",
        "_draining",
        "_feed",
        "_indicator",
        "_input_lock",
        "_inputs_closed",
        "_jobs",
        "_keyboard_overlay",
        "_keymap",
        "_notifications",
        "_overlay_enabled",
        "_poll_timer",
        "_recording",
        "_root",
        "_switcher",
        "_thread",
        "_views",
        "_work",
        "_work_connection",
        "_work_lock",
        "_work_view",
    )

    def __init__(self, *, views: Views | None = None) -> None:
        # Ui owns independent toolbar and feed lifetimes; their concrete
        # factories and native effects enter here before any view is created.
        self._views: Views = Views() if views is None else views
        if threading.current_thread() is not threading.main_thread():
            raise RuntimeError("Qt must be created on the process's main thread.")
        self._agent: AgentWindow | None = None
        # Qt owns the latest capture observation, including before the canvas
        # exists, so opening it during a held speech key starts in that state.
        self._agent_speaking: bool = False
        # Qt's thread owns the feed observation; every observer's report arrives there.
        self._feed: PendingFeed = PendingFeed()
        self._assess: Assess | None = None
        self._notifications: NotificationSources | None = None
        self._desktop: DesktopBar | None = None
        self._automatic_recording = AutomaticStatus.OFF
        self._overlay_enabled = False
        self._switcher: WindowSwitcher | None = None
        self._agent_lock = threading.Lock()
        self._work: WorkWindow | None = None
        self._work_connection: WorkConnection | None = None
        self._work_view: CanvasWindow | None = None
        self._canvas: CanvasEdits | None = None
        self._canvas_session: Callable[[Snapshot], bool] | None = None
        self._canvas_notice: Callable[[str, str], None] | None = None
        self._canvas_published: CanvasPublication | None = None
        self._work_lock = threading.Lock()
        # The controller that owns these effects is created after Ui, on its own
        # thread, so it connects them through configure_controls.
        self._agent_waiting: Callable[[bool], None] | None = None
        self._recording: Callable[[RecordingAction], None] | None = None
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

    def configure_controls(
        self,
        *,
        on_agent_waiting: Callable[[bool], None],
        on_recording: Callable[[RecordingAction], None],
    ) -> None:
        """Connect the application before it creates any views."""
        self._agent_waiting, self._recording = on_agent_waiting, on_recording

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
            while not all(window.publication.closed_ready.is_set() for window in self._windows()):
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

    def agent(  # noqa: PLR0913 - one callback per window event
        self,
        stop: Callable[[], None],
        *,
        on_problem: Callable[[str], None] | None = None,
        on_reset: Callable[[], bool] | None = None,
        on_submit: Callable[[str], None] | None = None,
        on_work: Callable[[], None] | None = None,
        focus: bool = False,
        reveal: bool = True,
    ) -> AgentWindow:
        with self._agent_lock:
            if self._agent is None:
                self._agent = AgentWindow(
                    stop,
                    post=lambda job: self.post(lambda root: job()),
                    create_view=self._compose_feed,
                    on_problem=on_problem,
                    on_reset=on_reset,
                    on_submit=on_submit,
                    on_waiting=self._agent_waiting,
                    on_recording=self._recording,
                    on_work=on_work,
                )
                self.post(self._replay_canvas)
            panel = self._agent
        if reveal:
            panel.show(focus=focus)
        return panel

    def configure_feed(self, notifications: SavedState[NotificationState], assess: Assess) -> None:
        """Connect the notice store and triage before their observers start."""
        owner = NotificationSources(notifications)
        owner.load()
        self._notifications, self._assess = owner, assess

    def _observe_feed(self, update: FeedUpdate) -> None:
        self._feed = observe(self._feed, update)
        if self._assess is not None:
            self._assess(self._feed)

    def communications_changed(self, feed: assistant.communications.Feed) -> None:
        self.post(lambda _: self._observe_feed(TeamsObserved(feed)))

    def system_notices(self, observation: winapi.system_notices.Observed) -> None:
        def update(_: QtWidgets.QApplication) -> None:
            if self._notifications is not None and self._notifications.observe(observation):
                self._observe_feed(NoticesObserved(self._notifications.state))

        self.post(update)

    def refresh_inbox(self, session: Snapshot | None = None) -> None:
        """Publish attention on the Qt thread, including before the agent view exists."""
        if session is None:
            session = Session() if self._agent is None else self._agent.snapshot()
        if self._desktop is not None:
            self._desktop.agent_changed(island_agent.activity(session))
            self._desktop.requests_changed(tuple(phases(session)))
            self._desktop.notices_changed(island_agent.notices(session))
        if self._canvas_session is not None:
            self._canvas_session(session)

    def _windows(self) -> tuple[AgentWindow | WorkWindow, ...]:
        return tuple(window for window in (self._agent, self._work) if window is not None)

    def close_windows(self) -> None:
        """Close the agent and work windows; off the Qt thread, wait briefly for each view to release."""
        for window in self._windows():
            window.close()
        for window in self._windows():
            if self._closed.is_set():
                window.publication.abandon()
            elif threading.current_thread() is not self._thread:
                window.publication.closed_ready.wait(timeout=3)

    def configure_work(
        self,
        on_command: Callable[[WorkViewCommand], None],
        *,
        on_problem: Callable[[str], None] | None = None,
    ) -> None:
        """Connect work effects once, before publishers or recovery can request its window."""
        # The control thread configures these effects; callers on either thread
        # may request the controller. This lock owns that one-time lifecycle.
        with self._work_lock:
            if self._work_connection is not None:
                raise RuntimeError("Work is already configured.")
            self._work_connection = WorkConnection(on_command, on_problem)

    def work_window(self) -> WorkWindow:
        """Return the configured controller; native preparation and showing are explicit."""
        with self._work_lock:
            connection = self._work_connection
            if connection is None:
                raise RuntimeError("Work opens after its command owner is configured.")
            if self._work is None:
                self._work = WorkWindow(
                    connection.on_command,
                    post=lambda job: self.post(lambda root: job()),
                    create_view=self._create_work,
                    on_problem=connection.on_problem,
                    create_loading=lambda: WaitCursor(self._root),
                )
            return self._work

    def _create_work(self, work: WorkWindow) -> CanvasWindow:
        if self._canvas is None:
            raise RuntimeError("The canvas opens after its owner is configured.")
        self._work_view = self._views.canvas(self._root, work, self._canvas)
        self._work_view.voice_pressed(pressed=self._agent_speaking)
        return self._work_view

    def _compose_feed(self, agent: AgentWindow) -> SessionDisplay:
        return SessionDisplay(self.refresh_inbox, agent.show_work)

    def configure_canvas(self, canvas: CanvasEdits, notice: Callable[[str, str], None], *, observe_session: Callable[[Snapshot], bool]) -> None:
        """Connect edit commands and a session-observation sink before rendering starts."""

        def configure(_: QtWidgets.QApplication) -> None:
            self._canvas, self._canvas_notice, self._canvas_session = canvas, notice, observe_session
            session = self._agent.snapshot() if self._agent is not None else Session()
            observe_session(session)

        self.post(configure)

    def publish_canvas(self, publication: CanvasPublication) -> None:
        """Defer owner publications until callers have finished their gesture or command."""
        self.post(lambda _: self._publish_canvas(publication))

    def _replay_canvas(self, _: QtWidgets.QApplication) -> None:
        # Read on Qt when the callback executes: an earlier queued change may
        # have superseded the publication retained when the view was requested.
        if self._canvas_published is not None:
            self._publish_canvas(self._canvas_published, replay=True)

    def _publish_canvas(self, publication: CanvasPublication, *, replay: bool = False) -> None:
        """Replay attention to late-created views without repeating the original notice."""
        self._canvas_published = publication
        if self._agent is not None:
            self._agent.canvas_attention(publication.attention)
        if self._desktop is not None:
            self._desktop.inbox_changed(len(publication.waiting))
        if self._work_view is not None:
            self._work_view.show_document(publication.document)
        if not replay:
            focus = self._work_view.focus() if self._work_view is not None else None
            notice = desktop_ui.desktop_attention.interrupts(publication.notice, focus)
            if notice is not None and self._canvas_notice is not None:
                self._canvas_notice(notice.title, notice.target)

    def open_canvas_at(self, identity: str) -> None:
        self.show_canvas()

        def reveal(_: QtWidgets.QApplication) -> None:
            if self._work_view is not None:
                self._work_view.open_at(identity)

        self.post(reveal)

    def open_reference(self, url: str) -> None:
        """Qt delegates a validated original document/page to the desktop shell."""

        def open_original(_: QtWidgets.QApplication) -> None:
            if not QtGui.QDesktopServices.openUrl(QtCore.QUrl(url)) and self._work is not None:
                self._work.problem("The original reference could not be opened.")

        self.post(open_original)

    def voice_agent(self, text: str, fallback: Callable[[str], None]) -> None:
        """Route speech on Qt to the canvas context or conversation input.

        A rejected clarification reply is consumed here, so it cannot accidentally
        answer another question or become a new task. Dictation has its own path.
        """

        def route(_: QtWidgets.QApplication) -> None:
            if self._agent is not None:
                session = self._agent.snapshot()
                question = selected_question(session.attention, session.selected_request)
                if question is not None:
                    self.answer_canvas(question.request, text)
                    return
            view = self._work_view
            focus = view.focus() if view is not None else None
            waiting = self._canvas.waiting() if self._canvas is not None else ()
            target = desktop_ui.desktop_attention.speech_target(waiting, focus)
            match target:
                case desktop_ui.desktop_attention.AnswerQuestion(request=request):
                    if not self.answer_canvas(request, text) and view is not None:
                        view.reply_failed()
                case desktop_ui.desktop_attention.Speech.INSTRUCT:
                    if view is not None:
                        view.instruct(text)
                case desktop_ui.desktop_attention.Speech.CONVERSATION:
                    fallback(text)
                case _:
                    assert_never(target)

        self.post(route)

    def answer_canvas(self, request: CanvasRequest, value: str) -> bool:
        if self._canvas is None:
            return False
        try:
            answer = TextAnswer(value)
        except ValueError:
            return False
        return self._canvas.answer(request, answer, self._deliver_answer)

    def _deliver_answer(self, request: CanvasRequest, answer: TextAnswer) -> bool:
        session = self._agent.snapshot().identity if self._agent is not None else None
        target = desktop_ui.desktop_attention.delivery(request, answer, session)
        match target:
            case desktop_ui.desktop_attention.ToSession(session_id=identity, request_id=key):
                return self._agent is not None and self._agent.respond(key, answer, expected_session=identity)
            case desktop_ui.desktop_attention.ToTask(command=command):
                connection = self._work_connection
                if connection is None:
                    return False
                try:
                    connection.on_command(command)
                except (OSError, ValueError) as error:
                    if connection.on_problem is not None:
                        connection.on_problem(str(error))
                    return False
                return True
            case desktop_ui.desktop_attention.Undeliverable.STALE:
                return False
            case _:
                assert_never(target)

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
        session = self._agent.snapshot() if self._agent is not None else Session()
        asked = tuple(phase for phase in phases(session) if hint(phase.turn))
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
        if self._work is not None:
            self._work.show()
        elif self._agent is not None:
            self._agent.show_work()

    def request_action(self, action: OpenCanvas) -> None:
        if self._desktop is not None:
            self._desktop.close_menu(restore=False)
        self.open_canvas_at(action.target)

    def select_request(self, request: CanvasRequest | None) -> None:
        if self._agent is not None:
            self._agent.select_attention(request)

    # View navigation, stop, overlay, menu dispatch and error reporting remain
    # distinct effect ports; audio observation and tool dispatch complete bar composition.
    def desktop(  # noqa: PLR0913 - one callback per window event
        self,
        *,
        show_work: Callable[[], None],
        stop: Callable[[], None],
        overlay: Callable[[], None],
        menu: Callable[[], None],
        on_problem: Callable[[str], None],
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
                    show_work,
                    stop,
                    self._recording or (lambda _: None),
                    self.show_keymap,
                    overlay,
                    menu,
                    on_problem,
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
                on_problem("The Workspace bar could not start. The tray remains available.")

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

    def desktop_job(self, job: island_model.Job | None) -> None:
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
