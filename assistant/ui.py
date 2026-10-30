"""Qt owns the main thread; callers enqueue work or await explicit input.

No GUI objects cross the keyboard process. Domain work remains off the UI thread.
"""

import queue
import threading
import traceback
from collections.abc import Callable
from concurrent.futures import Future, TimeoutError
from dataclasses import dataclass, replace
from functools import partial
from pathlib import Path
from typing import Final, Protocol

lazy import shiboken6
lazy from PySide6 import QtCore, QtGui, QtWidgets
lazy from PySide6.QtCore import Qt

import winapi.shapes
from assistant.canvas_activity import CanvasRequest, SessionRequest, TaskRequest
from assistant.overlay import KeyHighlights, fit_position, nearest_work_area
from assistant.qt_runtime import prepare
from assistant.work_canvas_commands import CanvasCommand, CanvasRefused, CanvasResponse, CanvasUpdated
from assistant.work_canvas_model import CanvasDocument
from assistant.work_window import AnswerTask
from automation.personal_work import Catalog
from automation.task import TextAnswer
from winapi import windows
from winapi.shapes import Rect
lazy import assistant.communications
lazy import assistant.console_requests
lazy import assistant.system_notices
lazy from assistant.agent_session import Session, Snapshot
lazy from assistant.agent_toasts import AgentToasts
lazy from assistant.agent_window import AgentWindow
lazy from assistant.desktop_bar import BarActions, DesktopBar
lazy from assistant.feed_items import SourceAction
lazy from assistant.feed_triage import Board
lazy from assistant.geometry import region
lazy from assistant.icons import State
lazy from assistant.keymap import PHYSICAL_NAMES, Cap, Kind, keymap
lazy from assistant.meeting_panel import MeetingPanel
lazy from assistant.meeting_workflow import MeetingSnapshot, MeetingWorkflow
lazy from assistant.notification_sources import (
    HandleNotice,
    Notices,
    NotificationSources,
    NotificationState,
    OpenApp,
    ReopenNotice,
    ToggleApp,
    joined,
)
lazy from assistant.overlay_desktop import NativeOverlayDesktop, OverlayDesktop
lazy from assistant.qt_ui import application, cancel, later
lazy from assistant.recording_state import RecordingAction, RecordingState
lazy from assistant.state_store import SavedState
lazy from assistant.system_notices import NoticeKey
lazy from assistant.ui_components.appearance import CONTROL_STYLE, OVERLAY_ACCENT, OVERLAY_BACKGROUND, OVERLAY_INK, OVERLAY_MUTED, OVERLAY_SURFACE
lazy from assistant.ui_components.canvas_loading import CanvasLoading
lazy from assistant.ui_components.controls import button, label
lazy from assistant.ui_components.widgets import Editor, Window, column, row, show_window
lazy from assistant.vector_icons import icon
lazy from assistant.window_switcher import WindowSwitcher
lazy from assistant.work_canvas import AnswerQuestion, CanvasChange, SpeechRoute, WorkCanvas
lazy from assistant.work_canvas_window import CanvasWindow
lazy from assistant.work_window import WorkCommand, WorkSnapshot, WorkWindow
lazy from miryoku.layout import Layer, Scancode
lazy from protocol import Tool

prepare()


type Job = Callable[[QtWidgets.QApplication], None]


@dataclass(frozen=True, slots=True)
class _Answer[T]:
    value: T


@dataclass(frozen=True, slots=True)
class MeetingConnection:
    workflow: MeetingWorkflow
    open_file: Callable[[Path], None]


def _bring_forward(window: QtWidgets.QWidget, focus: QtWidgets.QWidget) -> None:
    show_window(window, focus=True, target=focus)


def _near_pointer(window: QtWidgets.QWidget, width: int, height: int) -> None:
    point = QtGui.QCursor.pos()
    display = QtWidgets.QApplication.screenAt(point) or window.screen()
    area = display.availableGeometry()
    window.resize(width, height)
    window.move(
        max(area.left(), min(point.x() - width // 2, area.right() - width)), max(area.top(), min(point.y() - height // 3, area.bottom() - height))
    )


class Presentation(Protocol):
    """Position and reveal native dialogs on their owning Qt thread."""

    def position(self, window: QtWidgets.QWidget, width: int, height: int) -> None: ...

    def reveal(self, window: QtWidgets.QWidget, focus: QtWidgets.QWidget) -> None: ...


class NativePresentation:
    __slots__ = ()

    def position(self, window: QtWidgets.QWidget, width: int, height: int) -> None:
        _near_pointer(window, width, height)

    def reveal(self, window: QtWidgets.QWidget, focus: QtWidgets.QWidget) -> None:
        _bring_forward(window, focus)


class DesktopFactory(Protocol):
    def __call__(self, actions: BarActions, *, audio_level: Callable[[], float | None] | None = None) -> DesktopBar: ...


def _native_desktop(actions: BarActions, *, audio_level: Callable[[], float | None] | None = None) -> DesktopBar:
    # Resolve the lazy native module only when Qt owns this view's construction.
    return DesktopBar(actions, audio_level=audio_level)


def _native_feed_view(root: QtWidgets.QApplication, agent: AgentWindow) -> AgentToasts:
    return AgentToasts(root, agent)


class Ui:
    __slots__ = (
        "_agent",
        "_agent_lock",
        "_agent_speaking",
        "_agent_waiting",
        "_canvas",
        "_canvas_notice",
        "_choose_work",
        "_closed",
        "_communication_action",
        "_communication_drafts",
        "_communication_feed",
        "_console_action",
        "_console_requests",
        "_desktop",
        "_desktop_factory",
        "_dialogs",
        "_dismiss_work",
        "_feed_factory",
        "_indicator",
        "_input_lock",
        "_inputs_closed",
        "_jobs",
        "_keyboard_overlay",
        "_keymap",
        "_meetings",
        "_notice_dismissal",
        "_notifications",
        "_pending_inputs",
        "_poll_timer",
        "_recording",
        "_root",
        "_switcher",
        "_teams_feed",
        "_thread",
        "_triage",
        "_triage_observe",
        "_work",
        "_work_lock",
        "_work_view",
        "presentation",
    )

    def __init__(
        self,
        *,
        on_agent_waiting: Callable[[bool], None] | None = None,
        on_recording: Callable[[RecordingAction], None] | None = None,
        presentation: Presentation | None = None,
        desktop_factory: DesktopFactory | None = None,
        feed_factory: Callable[[QtWidgets.QApplication, AgentWindow], AgentToasts] | None = None,
        dismiss_notice: Callable[[NoticeKey], None] | None = None,
    ) -> None:
        # Ui owns independent dialog, toolbar and feed lifetimes; their concrete
        # factories and native effects enter here before any view is created.
        self.presentation: Presentation = NativePresentation() if presentation is None else presentation
        self._desktop_factory: DesktopFactory = _native_desktop if desktop_factory is None else desktop_factory
        self._feed_factory: Callable[[QtWidgets.QApplication, AgentWindow], AgentToasts] = _native_feed_view if feed_factory is None else feed_factory
        self._notice_dismissal: Callable[[NoticeKey], None] | None = dismiss_notice
        if threading.current_thread() is not threading.main_thread():
            raise RuntimeError("Qt must be created on the process's main thread.")
        self._agent: AgentWindow | None = None
        # Qt owns the latest capture observation, including before the canvas
        # exists, so opening it during a held speech key starts in that state.
        self._agent_speaking: bool = False
        self._communication_action: Callable[[assistant.communications.Command], bool] | None = None
        self._communication_feed = self._teams_feed = assistant.communications.Feed()
        self._communication_drafts: dict[str, str] = {}
        self._notifications: NotificationSources | None = None
        self._console_action: Callable[[assistant.console_requests.Command], bool] | None = None
        self._console_requests: tuple[assistant.console_requests.Request, ...] = ()
        self._triage = Board()
        self._triage_observe: Callable[[assistant.communications.Feed, tuple[assistant.console_requests.Request, ...]], None] | None = None
        self._choose_work: Callable[[str, str, str], bool] | None = None
        self._dismiss_work: Callable[[str], bool] | None = None
        self._desktop: DesktopBar | None = None
        self._switcher: WindowSwitcher | None = None
        self._agent_lock = threading.Lock()
        self._work: WorkWindow | None = None
        self._work_view: CanvasWindow | None = None
        self._canvas: WorkCanvas | None = None
        self._canvas_notice: Callable[[str, str], None] | None = None
        self._meetings: MeetingConnection | None = None
        self._work_lock = threading.Lock()
        self._agent_waiting, self._recording = on_agent_waiting, on_recording
        self._indicator: Indicator | None = None
        """Made on first use, on the Qt thread."""
        self._keymap: KeymapWindow | None = None
        self._keyboard_overlay: KeymapOverlay | None = None
        self._jobs: queue.Queue[Job] = queue.Queue()
        self._closed, self._inputs_closed = threading.Event(), False
        self._input_lock = threading.Lock()
        self._pending_inputs: set[Callable[[], None]] = set()
        self._dialogs: list[QtWidgets.QWidget] = []
        self._thread = threading.current_thread()
        self._root = application()
        self._root.setStyleSheet(CONTROL_STYLE)
        self._poll_timer = QtCore.QTimer(self._root)
        self._poll_timer.setInterval(20)
        self._poll_timer.timeout.connect(lambda: self._poll(self._root))
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
                    self._close_views()
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

    def _close_views(self) -> None:
        try:
            self.close_desktop()
        finally:
            self.close_agent()
            self.close_work()
            self._work_view = None
            while (self._agent is not None and not self._agent.closed_ready.is_set()) or (
                self._work is not None and not self._work.closed_ready.is_set()
            ):
                self._poll(self._root)

    def _close_inputs(self) -> None:
        with self._input_lock:
            self._inputs_closed = True
            pending = tuple(self._pending_inputs)
        for cancel_input in pending:
            cancel_input()

    def _poll(self, root: QtWidgets.QApplication) -> None:
        for _ in range(64):
            try:
                job = self._jobs.get_nowait()
            except queue.Empty:
                break
            try:
                job(root)
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

    def _ask[T](
        self,
        build: Callable[[QtWidgets.QApplication, Callable[[T], None]], None],
        *,
        on_close: Callable[[], T] | None = None,
    ) -> T:
        """Builds a window on the Qt thread and waits for the answer it gives."""
        answers: queue.Queue[_Answer[T] | Exception] = queue.Queue()

        def finish(result: _Answer[T] | Exception) -> None:
            with self._input_lock:
                if cancel_input not in self._pending_inputs:
                    return
                self._pending_inputs.remove(cancel_input)
            answers.put(result)

        def cancel_input() -> None:
            if on_close is not None:
                finish(_Answer(on_close()))
            else:
                finish(OSError("The Qt UI is closed."))

        def job(root: QtWidgets.QApplication) -> None:
            with self._input_lock:
                if cancel_input not in self._pending_inputs:
                    return
            try:
                build(root, lambda value: finish(_Answer(value)))
            except Exception as error:
                finish(error)

        with self._input_lock:
            if self._inputs_closed:
                if on_close is not None:
                    return on_close()
                raise OSError("The Qt UI is closed.")
            self._pending_inputs.add(cancel_input)
        self.post(job)
        try:
            result = answers.get()
        finally:
            with self._input_lock:
                self._pending_inputs.discard(cancel_input)
        match result:
            case Exception():
                raise result
            case _Answer(value):
                return value

    # ---- a text box --------------------------------------------------------------------

    def prompt(self, title: str) -> str | None:
        def build(root: QtWidgets.QApplication, done: Callable[[str | None], None]) -> None:
            dialog = QtWidgets.QInputDialog()
            dialog.setWindowTitle("Workspace")
            dialog.setLabelText(title)
            dialog.setInputMode(QtWidgets.QInputDialog.InputMode.TextInput)
            dialog.setStyleSheet(CONTROL_STYLE)
            self._dialogs.append(dialog)

            def finish(result: int) -> None:
                done(dialog.textValue().strip() if result == QtWidgets.QDialog.DialogCode.Accepted else None)
                self._dialogs.remove(dialog)
                dialog.deleteLater()

            dialog.finished.connect(finish)
            self.presentation.position(dialog, 640, 130)
            dialog.open()
            self.presentation.reveal(dialog, dialog)

        return self._ask(build, on_close=lambda: None)

    def choose_region(self, screen: Rect) -> Rect | None:
        def build(root: QtWidgets.QApplication, done: Callable[[Rect | None], None]) -> None:
            picker = RegionPicker(screen, lambda value: later(root, 150, lambda: done(value)))
            self._dialogs.append(picker)
            picker.destroyed.connect(lambda: self._dialogs.remove(picker))
            show_window(picker, focus=True)

        return self._ask(build, on_close=lambda: None)

    # ---- an answer, with follow-ups ----------------------------------------------------

    def answer(self, title: str, follow_up: Callable[[str], None]) -> AnswerWindow:
        def build(root: QtWidgets.QApplication, done: Callable[[AnswerWindow], None]) -> None:
            done(AnswerWindow(self, root, title, follow_up))

        return self._ask(build)

    # ---- the key map and the layer indicator ------------------------------------------

    def show_keymap(self) -> None:
        def job(root: QtWidgets.QApplication) -> None:
            if self._keymap is None or not shiboken6.isValid(self._keymap.window):
                self._keymap = KeymapWindow(root)
            else:
                _bring_forward(self._keymap.window, self._keymap.canvas)

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
        self.post(lambda _: self._desktop.layer(text) if self._desktop is not None else None)

    def flash(self, text: str, work: Rect, seconds: float = 1.2) -> None:
        """Shows a message in the indicator for a moment."""
        self.post(lambda root: self._overlay(root).flash(text, work, seconds))

    def agent(
        self,
        task: str | None,
        stop: Callable[[], None],
        *,
        on_problem: Callable[[str], None] | None = None,
        on_reset: Callable[[], bool] | None = None,
        on_submit: Callable[[str], None] | None = None,
        on_work: Callable[[], None] | None = None,
        focus: bool = False,
        reveal: bool = True,
        queued: bool = False,
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
                    on_communication=self.communicate,
                    on_snapshot=self.refresh_inbox,
                )
                self._agent.communications(self._communication_feed, self._communication_drafts)
                self._agent.on_console = self._console_action
                self._agent.consoles(self._console_requests)
                self._agent.triage(self._triage)
                self._agent.on_dismiss_work = self._dismiss_work
                self._agent.on_choose_work = self._choose_work
            panel = self._agent
        if task is not None:
            panel.begin(task, stop, queued=queued)
        if reveal:
            panel.show(focus=focus)
        return panel

    def configure_triage(
        self,
        observe: Callable[[assistant.communications.Feed, tuple[assistant.console_requests.Request, ...]], None],
        dismiss: Callable[[str], bool] | None = None,
        choose: Callable[[str, str, str], bool] | None = None,
    ) -> None:
        self._triage_observe = observe
        self._dismiss_work = dismiss
        self._choose_work = choose
        if self._agent is not None:
            self._agent.on_dismiss_work = dismiss
            self._agent.on_choose_work = choose

    def triage_changed(self, board: Board) -> None:
        def update(_: QtWidgets.QApplication) -> None:
            self._triage = board
            if self._agent is not None:
                self._agent.triage(board)
            self.refresh_inbox()

        self.post(update)

    def observe_triage(self) -> None:
        if self._triage_observe is not None:
            self._triage_observe(self._communication_feed, self._console_requests)

    def configure_communications(
        self, action: Callable[[assistant.communications.Command], bool], notifications: SavedState[NotificationState]
    ) -> None:
        """Connect the Teams worker and the Windows notice owner whose work this feed joins."""
        owner = NotificationSources(notifications, self.dismiss_system_notice)
        owner.load()
        self._communication_action, self._notifications = action, owner
        if self._agent is not None:
            self._agent.on_communication = self.communicate

    def communicate(self, command: SourceAction) -> bool:
        match command:
            case HandleNotice() | ReopenNotice() | OpenApp() | ToggleApp():
                if self._notifications is None or not self._notifications.command(command):
                    return False
                self.publish_feed()
                return True
            case _:
                return self._communication_action is not None and self._communication_action(command)

    def publish_feed(self) -> None:
        """Join Teams work and Windows notices on Qt's thread, where both observations arrive."""
        notices = self._notifications.state if self._notifications is not None else Notices()
        self._communication_feed = joined(self._teams_feed, notices)
        self.observe_triage()
        if self._agent is not None:
            self._agent.communications(self._communication_feed, self._communication_drafts)
        self.refresh_inbox()

    def communications_changed(self, feed: assistant.communications.Feed, drafts: dict[str, str]) -> None:
        def update(_: QtWidgets.QApplication) -> None:
            self._teams_feed, self._communication_drafts = feed, drafts
            self.publish_feed()

        self.post(update)

    def system_notices(self, observation: assistant.system_notices.Observed) -> None:
        def update(_: QtWidgets.QApplication) -> None:
            if self._notifications is not None and self._notifications.observe(observation):
                self.publish_feed()

        self.post(update)

    def configure_console(self, action: Callable[[assistant.console_requests.Command], bool]) -> None:
        self._console_action = action
        if self._agent is not None:
            self._agent.on_console = action

    def console_changed(self, requests: tuple[assistant.console_requests.Request, ...]) -> None:
        def update(_: QtWidgets.QApplication) -> None:
            self._console_requests = requests
            self.observe_triage()
            if self._agent is not None:
                self._agent.consoles(requests)
            self.refresh_inbox()

        self.post(update)

    def refresh_inbox(self, session: Snapshot | None = None) -> None:
        """Publish attention on the Qt thread, including before the agent view exists."""
        if session is None:
            if self._agent is None:
                session = Session()
            else:
                with self._agent.lock:
                    session = self._agent.state
        session = replace(session, communications=self._communication_feed, console_requests=self._console_requests, triage=self._triage)
        document = self._canvas.observe_session(session) if self._canvas is not None else None
        if document is not None:
            self.render_canvas_document(document)
        self.refresh_canvas_attention()

    def dismiss_system_notice(self, key: NoticeKey) -> None:
        if self._notice_dismissal is not None:
            self._notice_dismissal(key)
        else:
            self.post(lambda _: self._desktop.remove_notification(key) if self._desktop is not None else None)

    def handle_system_notice(self, key: NoticeKey) -> bool:
        if self._desktop is None or self._desktop.notification_observation is None:
            return False
        notice = next((item for item in self._desktop.notification_observation.notices if item.key == key), None)
        return notice is not None and self.communicate(HandleNotice(notice))

    def close_agent(self) -> None:
        if self._agent is not None:
            self._agent.close()
            if self._closed.is_set():
                self._agent.closed_ready.set()
            elif threading.current_thread() is not self._thread:
                self._agent.closed_ready.wait(timeout=3)

    def work(
        self,
        on_command: Callable[[WorkCommand], None],
        *,
        on_problem: Callable[[str], None] | None = None,
        focus: bool = True,
        reveal: bool = True,
    ) -> WorkWindow:
        with self._work_lock:
            if self._work is None:
                self._work = WorkWindow(
                    on_command,
                    post=lambda job: self.post(lambda root: job()),
                    create_view=self._create_work,
                    on_problem=on_problem,
                    create_loading=self._create_canvas_loading,
                )
            work = self._work
        if reveal:
            work.show(focus=focus)
        return work

    def _create_canvas_loading(self) -> CanvasLoading:
        return CanvasLoading(self._root, paint_frame=self._paint_canvas_loading)

    def _paint_canvas_loading(self) -> None:
        # Native exposure must run before blocking setup. Keep queued canvas
        # redirects/publications on the outer dispatcher until its view exists.
        active = self._poll_timer.isActive()
        self._poll_timer.stop()
        try:
            self._root.processEvents(QtCore.QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
        finally:
            if active:
                self._poll_timer.start()

    def _create_work(self, work: WorkWindow) -> CanvasWindow:
        if self._canvas is None:
            raise RuntimeError("The canvas opens after its owner is configured.")
        self._work_view = CanvasWindow(self._root, work, self._canvas)
        self._work_view.personal.voice_hint.set_pressed(pressed=self._agent_speaking)
        self._attach_meetings()
        return self._work_view

    def _compose_feed(self, agent: AgentWindow) -> AgentToasts:
        view = self._feed_factory(self._root, agent)
        view.use_canvas(self.open_canvas_at)
        return view

    def configure_canvas(self, canvas: WorkCanvas, notice: Callable[[str, str], None]) -> None:
        # The canvas owner holds storage and policy; Qt serializes its use.
        def configure(_: QtWidgets.QApplication) -> None:
            self._canvas, self._canvas_notice = canvas, notice
            session = self._agent.state if self._agent is not None else Session()
            self.render_canvas_document(canvas.observe_session(session) or canvas.read())
            self.refresh_canvas_attention()

        self.post(configure)

    def canvas_command(self, command: CanvasCommand) -> CanvasResponse:
        """Marshal bridge operations to Qt, never saving a worker's stale snapshot."""
        if threading.current_thread() is self._thread:
            return self.apply_canvas_command(command)
        result: Future[CanvasResponse] = Future()

        def execute(_: QtWidgets.QApplication) -> None:
            if not result.set_running_or_notify_cancel():
                return
            try:
                response = self.apply_canvas_command(command)
            except Exception as error:
                result.set_exception(error)
            else:
                result.set_result(response)

        self.post(execute)
        try:
            return result.result(timeout=8)
        except TimeoutError:
            # A queued command is cancelled before applying. If already running,
            # transport failure stays uncertain; never claim it was rejected.
            result.cancel()
            raise

    def apply_canvas_command(self, command: CanvasCommand) -> CanvasResponse:
        canvas = self._canvas
        if canvas is None:
            return CanvasRefused("The local canvas is unavailable.")
        response = canvas.command(command)
        match response:
            case CanvasUpdated():
                # Return the committed receipt before a later Qt refresh reflows.
                self.post(lambda _: self.render_canvas_document(canvas.read()))
            case _:
                pass
        return response

    def render_canvas_document(self, document: CanvasDocument) -> None:
        if self._agent is not None and self._canvas is not None:
            self._agent.settle_canvas(self._canvas.settled(document))
        if self._work_view is not None:
            self._work_view.personal.show_document(document)

    def refresh_canvas_attention(self) -> None:
        if self._desktop is not None:
            self._desktop.inbox_changed(len(self._canvas.waiting()) if self._canvas is not None else 0)

    def announce_canvas(self, change: CanvasChange) -> None:
        self.render_canvas_document(change.document)
        self.refresh_canvas_attention()
        notice = change.notice
        if notice is not None and self._canvas_notice is not None and (self._work_view is None or not self._work_view.window.isActiveWindow()):
            self._canvas_notice(notice.title, notice.target)

    def observe_canvas_work(self, snapshot: WorkSnapshot) -> None:
        def observe(_: QtWidgets.QApplication) -> None:
            if self._canvas is not None:
                self.announce_canvas(self._canvas.observe_work(snapshot))

        self.post(observe)

    def observe_canvas(self, catalog: Catalog) -> None:
        def observe(_: QtWidgets.QApplication) -> None:
            if self._canvas is not None:
                self.announce_canvas(self._canvas.observe_catalog(catalog))

        self.post(observe)

    def open_canvas_at(self, identity: str) -> None:
        if self._work is None:
            if self._agent is not None:
                self._agent.show_work()
        else:
            self._work.show()

        def reveal(_: QtWidgets.QApplication) -> None:
            if self._work_view is not None:
                self._work_view.personal.open_at(identity)

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
            panel = self._work_view.personal if self._work_view is not None else None
            if self._canvas is None or panel is None:
                fallback(text)
                return
            match self._canvas.speech(panel.selected, visible=panel.frame.isVisible()):
                case AnswerQuestion(request=request):
                    if not self.answer_canvas(request, text):
                        panel.status.setText("This reply could not be sent. Your transcript is available with Copy latest transcript.")
                case SpeechRoute.INSTRUCT:
                    panel.send_instruction(text)
                case SpeechRoute.FALLBACK:
                    fallback(text)

        self.post(route)

    def answer_canvas(self, request: CanvasRequest, value: str) -> bool:
        if self._canvas is None:
            return False
        document = self._canvas.answer(request, value, self._deliver_answer)
        if document is None:
            return False
        self.render_canvas_document(document)
        self.refresh_canvas_attention()
        return True

    def _deliver_answer(self, request: CanvasRequest, value: str) -> bool:
        match request:
            case SessionRequest(session_id=identity, request_id=key):
                return self._agent is not None and self._agent.state.identity == identity and self._agent.respond(key, value)
            case TaskRequest(task_id=task, request_id=key):
                if self._work is None:
                    return False
                try:
                    answer = TextAnswer(value)
                except ValueError:
                    return False
                return self._work.send(AnswerTask(task, key, answer))

    def _attach_meetings(self) -> None:
        connection, view = self._meetings, self._work_view
        if connection is not None and view is not None and view.meetings is None:
            view.attach_meetings(MeetingPanel(connection.workflow, open_file=connection.open_file))

    def configure_meetings(self, workflow: MeetingWorkflow, open_file: Callable[[Path], None]) -> None:
        def configure(_: QtWidgets.QApplication) -> None:
            self._meetings = MeetingConnection(workflow, open_file)
            self._attach_meetings()

        self.post(configure)

    def meetings_changed(self, snapshot: MeetingSnapshot) -> None:
        def render(_: QtWidgets.QApplication) -> None:
            if self._work_view is not None and self._work_view.meetings is not None:
                self._work_view.meetings.render_snapshot(snapshot)

        self.post(render)

    def show_meetings(self) -> None:
        def reveal(_: QtWidgets.QApplication) -> None:
            if self._work_view is not None:
                self._work_view.show_meetings()

        self.post(reveal)

    def close_work(self) -> None:
        if self._work is not None:
            self._work.close()
            if self._closed.is_set():
                self._work.closed_ready.set()
            elif threading.current_thread() is not self._thread:
                self._work.closed_ready.wait(timeout=3)

    def open_inbox(self, show_agent: Callable[[], None]) -> None:
        """Bell and keyboard requests share Qt-owned initialization and inbox focus."""

        def reveal(_: QtWidgets.QApplication) -> None:
            with self._input_lock:
                if self._inputs_closed:
                    return
            waiting = self._canvas.waiting() if self._canvas is not None else ()
            if waiting:
                self.open_canvas_at(waiting[0].id)
            elif self._work is not None:
                self._work.show()
            else:
                show_agent()

        self.post(reveal)

    def desktop(
        self,
        *,
        show_agent: Callable[[], None],
        show_work: Callable[[], None],
        stop: Callable[[], None],
        overlay: Callable[[], None],
        menu: Callable[[], None],
        on_problem: Callable[[str], None],
        audio_level: Callable[[], float | None] | None = None,
        tiling: Callable[[Tool, int], None] | None = None,
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
                    show_agent,
                    show_work,
                    stop,
                    self._recording or (lambda _: None),
                    self.show_keymap,
                    overlay,
                    menu,
                    on_problem,
                    tiling or (lambda _tool, _hwnd: None),
                    self.system_notices,
                    self.handle_system_notice,
                    inbox=lambda: self.open_inbox(show_agent),
                )
                self._desktop = self._desktop_factory(actions, audio_level=audio_level)
                self.refresh_inbox()
            except Exception:
                traceback.print_exc()
                on_problem("The Workspace bar could not start. The tray remains available.")

        self.post(create)

    def desktop_state(self, state: State, *, agent_speaking: bool = False) -> None:
        def display(_: QtWidgets.QApplication) -> None:
            self._agent_speaking = agent_speaking
            if self._desktop is not None:
                self._desktop.state(state)
            if self._work_view is not None:
                self._work_view.personal.voice_hint.set_pressed(pressed=agent_speaking)

        self.post(display)

    def desktop_recording(self, recording: RecordingState) -> None:
        self.post(lambda _: self._desktop.recording_changed(recording) if self._desktop is not None else None)

    def desktop_layout(self, *, enabled: bool) -> None:
        self.post(lambda _: self._desktop.layout(enabled=enabled) if self._desktop is not None else None)

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
            _near_pointer(current, current.width(), current.height())
            _bring_forward(current, current.search)

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


class RegionPicker(QtWidgets.QWidget):
    def __init__(self, area: Rect, done: Callable[[Rect | None], object]) -> None:
        super().__init__()
        self.area, self.done = area, done
        self.start: QtCore.QPointF | None = None
        self.current: QtCore.QPointF | None = None
        self.finished = False
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCursor(Qt.CursorShape.CrossCursor)
        windows.move(int(self.winId()), area)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        painter.fillRect(self.rect(), QtGui.QColor(0, 0, 0, 76))
        if self.start is not None and self.current is not None:
            painter.setPen(QtGui.QPen(QtGui.QColor("#ffffff"), 2))
            painter.drawRect(QtCore.QRectF(self.start, self.current).normalized())

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.RightButton:
            self.finish(None)
        else:
            self.start = self.current = event.position()
            self.update()

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
        self.current = event.position()
        self.update()

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        if self.start is not None and event.button() == Qt.MouseButton.LeftButton:
            scale = self.devicePixelRatioF()
            first = (self.area.left + round(self.start.x() * scale), self.area.top + round(self.start.y() * scale))
            last = (self.area.left + round(event.position().x() * scale), self.area.top + round(event.position().y() * scale))
            area = region(first, last)
            self.finish(area if area.width > 4 and area.height > 4 else None)

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.finish(None)

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        self.finish(None)
        event.accept()

    def finish(self, area: Rect | None) -> None:
        if not self.finished:
            self.finished = True
            self.hide()
            self.done(area)
            self.deleteLater()


class AnswerWindow:
    __slots__ = (
        "__weakref__",
        "entry",
        "follow_up",
        "text",
        "ui",
        "window",
    )

    def __init__(self, ui: Ui, root: QtWidgets.QApplication, title: str, follow_up: Callable[[str], None]) -> None:
        self.ui, self.follow_up = ui, follow_up
        self.window = Window(title[:80], self.close, width=760, height=540)
        layout = column(self.window)
        layout.setContentsMargins(20, 18, 20, 18)
        self.text = Editor(readonly=True)
        layout.addWidget(self.text, 1)
        bottom = row()
        self.entry = QtWidgets.QLineEdit()
        self.entry.setPlaceholderText("Ask a follow-up…")
        self.entry.setEnabled(False)
        self.entry.returnPressed.connect(self.ask)
        bottom.addWidget(self.entry, 1)
        bottom.addWidget(button("Copy answer", self.copy_all))
        layout.addLayout(bottom)
        self.add(f"{title}\n\n", "accent")
        ui.presentation.position(self.window, 760, 540)
        ui.presentation.reveal(self.window, self.text)

    def close(self) -> None:
        self.window.hide()
        self.window.deleteLater()

    def add(self, text: str, tag: str = "") -> None:
        def job(_: QtWidgets.QApplication) -> None:
            if shiboken6.isValid(self.window):
                cursor = self.text.textCursor()
                cursor.movePosition(QtGui.QTextCursor.MoveOperation.End)
                cursor.insertText(text)
                self.text.setTextCursor(cursor)
                self.text.ensureCursorVisible()

        self.ui.post(job)

    def all_text(self) -> str:
        return self.text.toPlainText()

    def copy_all(self) -> None:
        QtWidgets.QApplication.clipboard().setText(self.all_text())

    def ask(self) -> None:
        if question := self.entry.text().strip():
            self.entry.clear()
            self.entry.setEnabled(False)
            self.add(f"\n\n{question}\n\n", "accent")
            self.follow_up(question)

    def write(self, text: str) -> None:
        self.add(text)

    def finish(self) -> None:
        def job(_: QtWidgets.QApplication) -> None:
            if shiboken6.isValid(self.window):
                self.entry.setEnabled(True)
                self.entry.setFocus()

        self.ui.post(job)

    def fail(self, message: str) -> None:
        self.add(f"\n{message}\n", "error")
        self.finish()


class Indicator:
    __slots__ = (
        "__weakref__",
        "_flash",
        "_frame",
        "_label",
        "_steady",
        "_window",
    )

    def __init__(self, root: QtWidgets.QApplication) -> None:
        self._window = QtWidgets.QWidget()
        self._window.setObjectName("workspaceWindow")
        self._window.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
        self._window.setStyleSheet(CONTROL_STYLE)
        self._window.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._window.setWindowOpacity(0.9)
        layout = row(self._window)
        layout.setContentsMargins(16, 6, 16, 6)
        self._label = label("")
        layout.addWidget(self._label)
        self._frame = int(self._window.winId())
        windows.make_overlay(self._frame)
        self._steady: tuple[str | None, Rect] | None = None
        self._flash: QtCore.QTimer | None = None

    def _show(self, text: str | None, work: Rect, colour: str = OVERLAY_INK) -> None:
        if text is None:
            self._window.hide()
            return
        self._label.setText(text)
        self._label.setStyleSheet(f"color: {colour}; font: 15px 'Segoe UI';")
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
            self._show(text, work)

    def flash(self, text: str, work: Rect, seconds: float) -> None:
        cancel(self._flash)
        self._show(text, work, OVERLAY_ACCENT)
        self._flash = later(self._window, round(seconds * 1000), self._end_flash)

    def _end_flash(self) -> None:
        self._flash = None
        if self._steady is not None:
            self._show(*self._steady)
        else:
            self._window.hide()


_COLOURS: Final = {
    Kind.KEY: (OVERLAY_SURFACE, OVERLAY_INK),
    Kind.MOD: ("#21403a", "#8fe3c6"),
    Kind.LAYER: ("#22324d", "#9cc3ff"),
    Kind.TOOL: ("#47381c", "#ffcf7a"),
    Kind.APP: ("#2c3f23", "#b6e39a"),
    Kind.SPECIAL: ("#3b2948", "#d7b4ff"),
    Kind.HELD: (OVERLAY_ACCENT, OVERLAY_BACKGROUND),
    Kind.BLANK: ("#191b1e", OVERLAY_MUTED),
}
_LAYERS: Final[tuple[tuple[str, Layer | None], ...]] = (("Base", None), *((layer.name.title(), layer) for layer in Layer))
_ROW_START: Final = (0.0, 1.5, 0.0, 1.25, 3.5)
"""Where each row starts, in key widths, as on an ISO keyboard."""
_UNIT, _GAP, _HEIGHT = 64, 5, 56


class KeymapCanvas(QtWidgets.QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.caps: dict[str, Cap] = {}
        self.boxes: dict[str, QtCore.QRectF] = {}
        self.highlighted: frozenset[str] = frozenset()
        self.scale = 1.0
        self.setAccessibleName("Physical keyboard and current layer")

    def draw(self, layer: Layer | None, scale: float = 1.0) -> None:
        self.scale = scale
        self.caps.clear()
        self.boxes.clear()
        for row_number, (caps, start) in enumerate(zip(keymap(layer), _ROW_START, strict=True)):
            x, y = start * _UNIT * scale, row_number * (_HEIGHT + _GAP) * scale
            for cap in caps:
                size = 6.25 if cap.physical == "Space" else 1.75 if cap.physical == "Caps" else 1.0
                self.caps[cap.physical] = cap
                self.boxes[cap.physical] = QtCore.QRectF(x, y, (size * _UNIT - _GAP) * scale, _HEIGHT * scale)
                x += size * _UNIT * scale
        self.setFixedSize(round(14 * _UNIT * scale), round(len(_ROW_START) * (_HEIGHT + _GAP) * scale))
        self.update()

    def colors(self, name: str) -> tuple[str, str]:
        return ("#ffcf7a", OVERLAY_BACKGROUND) if name in self.highlighted else _COLOURS[self.caps[name].kind]

    def press(self, names: frozenset[str]) -> None:
        changed = names ^ self.highlighted
        self.highlighted = names
        for name in changed:
            if name in self.boxes:
                self.update(self.boxes[name].toAlignedRect())

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        for name, cap in self.caps.items():
            bounds = self.boxes[name]
            fill, ink = self.colors(name)
            painter.setPen(QtGui.QPen(QtGui.QColor("#fff0cc" if name in self.highlighted else "#424b58"), 1))
            painter.setBrush(QtGui.QColor(fill))
            painter.drawRoundedRect(bounds.adjusted(0.5, 0.5, -0.5, -0.5), 4, 4)
            face = QtGui.QFont("Segoe UI")
            face.setPixelSize(max(8, round(10 * self.scale)))
            painter.setFont(face)
            painter.setPen(QtGui.QColor(ink if name in self.highlighted else OVERLAY_MUTED))
            painter.drawText(bounds.adjusted(5 * self.scale, 3 * self.scale, -3, -3), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, name)
            face.setPixelSize(max(8, round((15 if len(cap.label) <= 5 else 11) * self.scale)))
            face.setWeight(QtGui.QFont.Weight.DemiBold)
            painter.setFont(face)
            painter.setPen(QtGui.QColor(ink))
            painter.drawText(bounds, Qt.AlignmentFlag.AlignCenter, cap.label)
            face.setPixelSize(max(8, round(10 * self.scale)))
            face.setWeight(QtGui.QFont.Weight.Normal)
            painter.setFont(face)
            painter.drawText(bounds.adjusted(0, 0, 0, -3 * self.scale), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom, cap.hold)


@dataclass(frozen=True, slots=True)
class OverlayDrag:
    start: Callable[[QtCore.QPoint], None]
    move: Callable[[QtCore.QPoint], None]
    end: Callable[[], None]


class OverlayHandle(QtWidgets.QLabel):
    def __init__(self, drag: OverlayDrag, cursor: Callable[[], tuple[int, int]]) -> None:
        super().__init__("≡  Drag to move")
        self.drag: OverlayDrag = drag
        self.read_cursor: Callable[[], tuple[int, int]] = cursor
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setStyleSheet("background: #26313d; color: #cbd5e1; padding: 6px 12px; border-radius: 5px; font: 11px 'Segoe UI';")
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self.adjustSize()

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag.start(QtCore.QPoint(*self.read_cursor()))
            self.grabMouse()

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
        # The saved overlay position and native moves use physical pixels.
        self.drag.move(QtCore.QPoint(*self.read_cursor()))

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        self.releaseMouse()
        self.drag.end()


class KeymapOverlay:
    __slots__ = (
        "__weakref__",
        "_canvas",
        "_desktop",
        "_drag",
        "_frame",
        "_handle",
        "_handle_frame",
        "_heading",
        "_highlight_timer",
        "_highlights",
        "_position",
        "_view",
        "_window",
    )

    def __init__(self, root: QtWidgets.QApplication, desktop: OverlayDesktop | None = None) -> None:
        self._desktop: OverlayDesktop = desktop if desktop is not None else NativeOverlayDesktop()
        self._window = QtWidgets.QWidget()
        self._window.setObjectName("workspaceWindow")
        self._window.setWindowTitle("Workspace keyboard overlay")
        self._window.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
        self._window.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._window.setStyleSheet(CONTROL_STYLE)
        self._window.setWindowOpacity(0.55)
        layout = column(self._window)
        layout.setContentsMargins(8, 8, 8, 8)
        self._heading = label("", "muted")
        layout.addWidget(self._heading)
        self._canvas = KeymapCanvas()
        layout.addWidget(self._canvas)
        self._frame = self._desktop.prepare(self._window, click_through=True)
        self._handle = OverlayHandle(OverlayDrag(self._start_drag, self._drag_to, self._finish_drag), self._desktop.cursor)
        self._handle.setWindowTitle("Workspace keyboard overlay handle")
        self._handle_frame = self._desktop.prepare(self._handle, click_through=False)
        self._position = self._desktop.load_position()
        self._drag: QtCore.QPoint | None = None
        self._view: tuple[Layer | None, str, tuple[Rect, ...]] | None = None
        self._highlights = KeyHighlights()
        self._highlight_timer: QtCore.QTimer | None = None

    def show(self, layer: Layer | None, title: str, work: Rect, *, visible: bool, pressed: frozenset[Scancode] = frozenset()) -> None:
        if not visible:
            self._finish_drag()
            self.set_pressed(frozenset(), reset=True)
            self._handle.hide()
            self._window.hide()
            self._view = None
            return
        areas = self._desktop.work_areas() or (work,)
        view = (layer, title, areas)
        if view == self._view:
            self.set_pressed(pressed)
            return
        if self._position is not None:
            work = nearest_work_area(self._position, areas)
        density = self._window.devicePixelRatioF()
        scale = max(0.2, min(0.85, (work.width / density - 32) / (14 * _UNIT), (work.height / density - 180) / (4 * (_HEIGHT + _GAP))))
        self._heading.setText(f"Workspace keyboard · {title}")
        self._canvas.draw(layer, scale)
        self._view = view
        self.set_pressed(pressed)
        self._window.adjustSize()
        if self._position is None:
            self._position = (work.left + work.width // 2, work.bottom - round((self._window.height() + self._handle.height() + 90) * density))
        self._move(self._position)
        self._desktop.present(self._window)
        self._desktop.present(self._handle)

    def set_pressed(self, pressed: frozenset[Scancode], *, reset: bool = False) -> None:
        if reset:
            self._highlights.clear()
        if self._view is not None:
            self._highlights.update(pressed, self._desktop.clock())
            self._paint_highlights()

    def _paint_highlights(self) -> None:
        cancel(self._highlight_timer)
        self._highlight_timer = None
        now = self._desktop.clock()
        self._canvas.press(frozenset(PHYSICAL_NAMES[key] for key in self._highlights.visible(now)))
        if (delay := self._highlights.delay(now)) is not None:
            self._highlight_timer = later(self._window, delay, self._paint_highlights)

    def _move(self, position: tuple[int, int]) -> None:
        self._position = position
        x, y = position
        scale = self._window.devicePixelRatioF()
        width, height = round(self._window.width() * scale), round(self._window.height() * scale)
        handle_width, handle_height = round(self._handle.width() * scale), round(self._handle.height() * scale)
        left, top = x - width // 2, y + handle_height + 4
        self._desktop.move(self._frame, Rect(left, top, left + width, top + height))
        left = x - handle_width // 2
        self._desktop.move(self._handle_frame, Rect(left, y, left + handle_width, y + handle_height))

    def _start_drag(self, point: QtCore.QPoint) -> None:
        if self._position is not None and self._view is not None:
            self._drag = point - QtCore.QPoint(*self._position)

    def _drag_to(self, point: QtCore.QPoint) -> None:
        if self._drag is not None:
            value = point - self._drag
            self._move((value.x(), value.y()))

    def _finish_drag(self) -> None:
        if self._drag is None:
            return
        self._drag = None
        if self._position is not None:
            areas = self._desktop.work_areas()
            if areas:
                scale = self._window.devicePixelRatioF()
                self._move(
                    fit_position(
                        self._position,
                        (round(self._window.width() * scale), round((self._window.height() + self._handle.height() + 4) * scale)),
                        nearest_work_area(self._position, areas),
                    )
                )
            try:
                self._desktop.save_position(self._position)
            except OSError:
                traceback.print_exc()


class KeymapWindow:
    __slots__ = (
        "__weakref__",
        "buttons",
        "canvas",
        "layer",
        "shortcuts",
        "window",
    )

    def __init__(self, root: QtWidgets.QApplication) -> None:
        self.window = Window("Workspace key map", self.close, width=940, height=390)
        layout = column(self.window)
        layout.setContentsMargins(20, 16, 20, 16)
        buttons = row()
        self.buttons: list[QtWidgets.QToolButton] = []
        self.shortcuts: list[QtGui.QShortcut] = []
        for index, (name, layer) in enumerate(_LAYERS):
            choose = partial(self.draw, layer)
            key = button(name, choose)
            key.setCheckable(True)
            buttons.addWidget(key)
            self.buttons.append(key)
            shortcut = QtGui.QShortcut(QtGui.QKeySequence(str(index + 1)), self.window)
            shortcut.activated.connect(choose)
            self.shortcuts.append(shortcut)
        buttons.addStretch()
        layout.addLayout(buttons)
        self.canvas = KeymapCanvas()
        layout.addWidget(self.canvas)
        layout.addWidget(
            label(
                "Space: hold · B: dictate toggle · N: agent toggle · Apps + Esc: windows",
                "muted",
            )
        )
        self.layer: Layer | None = None
        self.draw(None)
        _near_pointer(self.window, 940, 390)
        _bring_forward(self.window, self.canvas)

    def draw(self, layer: Layer | None) -> None:
        self.layer = layer
        self.canvas.draw(layer)
        for key, (_, shown) in zip(self.buttons, _LAYERS, strict=True):
            key.setChecked(shown is layer)

    def close(self) -> None:
        self.window.hide()
        self.window.deleteLater()
