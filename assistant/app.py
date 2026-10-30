"""The assistant owns the tray, conversation views, microphone, and meetings.

Durable work executes in the supervised automation process. The keyboard sends
its tool requests here without depending on either work storage or model calls.
"""

import contextlib
import os
import queue
import threading
import time
import traceback
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from enum import Enum, auto
from pathlib import Path
from typing import Final, Protocol, assert_never

import keeper
import usage
from assistant.activity import ActivityTracker, ContextSnapshot, Observation
from config import APPS
from usage import DIRECTORY, Detail
lazy from assistant import activity, control_policy
lazy from assistant.browser import Browser
lazy from assistant.browser_session import Product
lazy from assistant.canvas_activity import CanvasInstruction, CanvasRun
lazy from assistant.communications_browser import TeamsWeb
lazy from assistant.communications_service import Communications
lazy from assistant.communications_state import COMMUNICATIONS_STATE
lazy from assistant.console_inbox import ConsoleInbox
lazy from assistant.desktop import WinDesktop
lazy from assistant.features import Assistant, switcher_windows
lazy from assistant.feed_contracts import STORED_BOARD
lazy from assistant.feed_research import Research
lazy from assistant.feed_triage import Candidate
lazy from assistant.feed_triage_service import Triage, classify
lazy from assistant.feed_work import FeedWork
lazy from assistant.icons import State, dot
lazy from assistant.keymap import indicator_text
lazy from assistant.lifecycle import Timings
lazy from assistant.llm import MAX_SECONDS, RATE, Missing, Settings
lazy from assistant.meeting_events import TranscriptEvents
lazy from assistant.meeting_followup_store import FollowupStore
lazy from assistant.meeting_requests import MeetingRequests
lazy from assistant.meeting_store import MeetingArchive
lazy from assistant.meeting_workflow import MeetingWorkflow
lazy from assistant.meetings import Meetings
lazy from assistant.monitor_layout import MonitorLayout
lazy from assistant.overlay import OverlayState, load_enabled, save_enabled
lazy from assistant.personal_work_model import Correlator
lazy from assistant.personal_work_service import PersonalWork
lazy from assistant.personal_work_sources import BrowserSources
lazy from assistant.recording_state import RecordingAction, RecordingState
lazy from assistant.report import write_report
lazy from assistant.state_store import windows_store
lazy from assistant.tiling import GlazeWM
lazy from assistant.ui import Ui
lazy from assistant.work_agent import WorkAgent
lazy from assistant.work_canvas import WorkCanvas, instruction_prompt
lazy from assistant.work_window import ControlTask, WorkCommand, WorkSnapshot
lazy from automation.bridge import BridgeClient
lazy from automation.context import ContextStore
lazy from automation.ipc import MeetingCommand, MeetingFailed, MeetingSucceeded, StartMeeting
lazy from automation.personal_work import (
    PERSONAL_REQUEST,
    AddDocument,
    AddWebPage,
    DismissWork,
    OpenWorkSource,
    PersonalStore,
    PersonalView,
    RefreshPersonalWork,
    RestoreWork,
    SaveWork,
    SourceKind,
    UnlinkWork,
    WorkThread,
)
lazy from automation.routines import RoutineStore
lazy from automation.store import TaskStore
lazy from automation.task import Control
lazy from keeper import ASSISTANT_WINDOW
lazy from miryoku.layout import Layer
lazy from protocol import WM_INDICATOR, WM_KEY_STATE, WM_LAYOUT_STATE, WM_REQUEST, LayoutState, Tool, decode_indicator
lazy from winapi import audio, recording, screen, shell, system, windows
lazy from winapi.shapes import Rect, Window

ROOT: Final = Path(__file__).resolve().parent.parent
LOCK_NAME: Final = "Local\\workspace-assistant"
LOG: Final = DIRECTORY / "assistant.log"
WM_TRAY: Final = system.WM_APP + 20


def log(text: str) -> None:
    """The assistant's own log: problems and crashes (there's no console under pythonw)."""
    with contextlib.suppress(OSError):
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as file:
            file.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {text}\n")


# ---- the tray icon ---------------------------------------------------------------------


class Tray:
    """The notification-area icon. Safe to use from any thread."""

    __slots__ = ("_icon", "_icons", "_lock")

    def __init__(self, window: int) -> None:
        self._icons = {state: shell.Icon(32, dot(32, state.value)) for state in State}
        self._lock = threading.Lock()
        self._icon = shell.TrayIcon(window, WM_TRAY, self._icons[State.READY], "Workspace")

    def show(self, state: State) -> None:
        with self._lock:
            self._icon.update(self._icons[state], f"Workspace: {state.name.lower().replace('_', ' ')}")

    def notify(self, title: str, text: str, *, warning: bool = False) -> None:
        with self._lock:
            self._icon.notify(title, text, shell.NIIF_WARNING if warning else shell.NIIF_INFO)

    def remove(self) -> None:
        with self._lock:
            self._icon.remove()
            for icon in self._icons.values():
                icon.destroy()


# ---- the request context ---------------------------------------------------------------


def foreground_context() -> Observation:
    """Keep Workspace's own windows from replacing the app a request refers to."""
    handle = windows.foreground()
    if not handle:
        return "unavailable"
    if windows.process_id(handle) == os.getpid():
        return "workspace"
    return Window(handle, windows.title(handle), windows.exe(handle), minimized=windows.is_minimized(handle))


# ---- the program -----------------------------------------------------------------------


class Exit(Enum):
    QUIT = auto()
    ALREADY_RUNNING = auto()


def indicator_area() -> Rect:
    """Where the layer indicator goes: the bottom of the main monitor."""
    monitors = screen.monitors()
    return next((m.work for m in monitors if m.primary), monitors[0].work)


WM_SHOW_MENU: Final = 0x8056


class NativeStartup:
    """Native timer, layout replay and readiness for the control-thread lifetime."""

    def find_window(self, title: str) -> int | None:
        return windows.find(title)

    # Match HWND, message and both payload fields of the native wire contract.
    def post(self, handle: int, message: int, wparam: int, lparam: int) -> bool:
        return system.post_message(handle, message, wparam, lparam)

    def start_timer(self, handle: int) -> int:
        return system.set_window_timer(handle, 1000)

    def ready(self) -> None:
        keeper.ready()


@dataclass(frozen=True, slots=True)
class WorkerStartup:
    """Start the controller's composed workers in their ownership order."""

    workers: tuple[Callable[[], None], ...]

    def start(self) -> None:
        for start in self.workers:
            start()


class AssistantApp:
    __slots__ = (
        "_recording_phase",
        "activity",
        "agent",
        "assistant",
        "canvas",
        "capture_timer",
        "communications",
        "consoles",
        "desktop",
        "followups",
        "jobs",
        "layout",
        "meetings",
        "mic_event",
        "monitor_layout",
        "overlay",
        "personal",
        "settings",
        "startup",
        "startup_effects",
        "tiling",
        "timings",
        "tray",
        "triage",
        "ui",
        "window",
        "worker",
    )

    def __init__(self, settings: Settings | Missing, ui: Ui, *, startup_effects: control_policy.StartupEffects | None = None) -> None:
        self.startup_effects: control_policy.StartupEffects = NativeStartup() if startup_effects is None else startup_effects
        self.timings = Timings("startup")
        self._recording_phase = "idle"
        self.ui = ui
        self.ui.configure_controls(
            on_agent_waiting=lambda waiting: self.show(State.NEEDS_INPUT if waiting else State.AGENT),
            on_recording=self.recording_action,
        )
        self.overlay = OverlayState(enabled=load_enabled())
        self.jobs: queue.Queue[Callable[[], None] | None] = queue.Queue()
        self.window = shell.AppWindow(ASSISTANT_WINDOW, self.on_message)
        self.tray = Tray(self.window.handle)
        self.mic_event = system.create_event()
        self.tiling = GlazeWM()
        self.monitor_layout = MonitorLayout(self.tiling, self.problem)
        mic = audio.Microphone(RATE, MAX_SECONDS, self.mic_event)
        self.desktop = WinDesktop(
            self.window.handle, mic, self.ui, on_state=self.show, on_notify=self.tray.notify, on_problem=self.problem, tiling=self.tiling
        )
        self.timings.mark("control window and microphone")
        missing = settings if isinstance(settings, Missing) else None
        self.settings = settings if isinstance(settings, Settings) else Settings("", "", "", "", "", "", "")
        self.activity: ActivityTracker

        def context() -> ContextSnapshot:
            # The tracker and runner refer to each other; observe after composition.
            return self.activity.snapshot()

        work_folder = DIRECTORY / "work"
        tasks = TaskStore(work_folder / "work.sqlite3")
        routines = RoutineStore(tasks.path)
        saved_context = ContextStore(tasks.path)
        self.agent = WorkAgent(
            tasks,
            routines,
            saved_context,
            BridgeClient(work_folder),
            lambda runner: self.ui.agent(
                None,
                runner.stop,
                on_problem=self.problem,
                on_reset=runner.new_conversation,
                on_submit=runner.start,
                on_work=self.show_work,
                reveal=False,
            ),
            on_snapshot=self.work_changed,
            on_done=self.agent_done,
            report_error=log,
            on_start=lambda: self.show(State.AGENT),
            context=context,
            meeting=self.meeting_command,
        )
        self.timings.mark("work frontend")
        self.activity = ActivityTracker(
            foreground_context,
            self.agent.running,
            policy=activity.Policy(enabled=os.environ.get("WORKSPACE_AGENT_CONTEXT", "recent").lower() != "off"),
        )
        self.communications = Communications(
            TeamsWeb(DIRECTORY / "browser-profile"),
            windows_store(DIRECTORY / "communications.bin", COMMUNICATIONS_STATE),
            self.ui.communications_changed,
            self.ui.dismiss_system_notice,
        )
        self.ui.configure_communications(self.communications.submit)
        self.consoles = ConsoleInbox(DIRECTORY / "inbox-bridge.json", self.ui.console_changed)
        self.ui.configure_console(self.consoles.command)
        self.canvas: WorkCanvas = WorkCanvas(
            work_folder / "canvas.sqlite3", self.continue_thread, autonomous=bool(self.settings.api_key and self.settings.base_url)
        )
        self.personal = self.create_personal(tasks)
        self.triage = Triage(
            DIRECTORY / "work-feed-bridge.json",
            windows_store(DIRECTORY / "work-feed.bin", STORED_BOARD),
            self.ui.triage_changed,
            self.review_feed,
            self.consoles.command,
            submit=self.agent.submit_identified,
            work=FeedWork(tasks, saved_context, context),
            personal=self.personal,
            canvas=self.ui.canvas_command,
        )
        self.ui.configure_triage(self.triage.observe, self.triage.dismiss, self.triage.choose_from_ui)
        self.timings.mark("communications and feed bridges")
        archive = MeetingArchive(DIRECTORY / "meetings")
        followup_folder = work_folder / "meeting-followups"
        self.followups = MeetingWorkflow(
            archive,
            MeetingRequests(followup_folder),
            FollowupStore(followup_folder / "packages"),
            submit_identified=self.agent.submit_identified,
            read_work=self.agent.snapshot,
            retain_work=lambda ids: self.agent.watch(ids, owner="meetings"),
            publish=self.ui.meetings_changed,
            report_error=log,
        )
        self.ui.configure_meetings(self.followups, self.open_meeting_file)
        events = TranscriptEvents(archive, routines, on_error=log, on_change=self.refresh_work)
        self.meetings = Meetings(
            self.settings,
            lambda source: recording.MeetingAudio(computer_audio=source == "both"),
            archive=archive,
            on_update=self.recording_changed,
            on_recovery=events.recover,
            on_complete=events.completed,
        )
        self.timings.mark("meeting services")
        self.assistant = Assistant(
            self.desktop,
            self.settings,
            record=self.record,
            submit=self.jobs.put,
            run_agent=self.voice_agent,
            show_agent=self.agent.show,
            stop_agent=self.agent.stop,
            missing=missing,
        )
        self.layout: LayoutState | None = None
        self.capture_timer: int | None = None
        """What the layout last said; None until it does."""
        self.worker = threading.Thread(target=self.work, name="worker", daemon=True)
        self.startup = WorkerStartup(
            (
                self.activity.start,
                self.worker.start,
                self.agent.start_worker,
                self.personal.start,
                self.communications.start,
                self.followups.start,
                self.meetings.start_worker,
                self.monitor_layout.start,
            )
        )
        if missing is not None:
            self.tray.notify("Workspace", f"The AI tools need {', '.join(missing.names)}; the layout works without them.", warning=True)

    # ---- running -----------------------------------------------------------------------

    def create_personal(self, tasks: TaskStore) -> PersonalWork:
        self.ui.configure_canvas(self.canvas, self.agent.notify_canvas)
        self.agent.watch(tuple(run.task_id for run in self.canvas.read().runs), owner="canvas")
        if self.settings.api_key and self.settings.base_url:
            # Recover only the crash window between binding and task commit.
            # Existing task prompts may have been redirected by the user.
            for run in self.canvas.read().runs:
                if (run.evidence is not None or isinstance(run.intent, CanvasInstruction)) and tasks.get(run.task_id) is None:
                    self.ui.post(self.canvas_recovery(run))
        return PersonalWork(
            PersonalStore(tasks.path),
            BrowserSources(Browser(DIRECTORY / "browser-profile", source=Product.EDGE)),
            self.personal_changed,
            model=Correlator(self.settings) if self.settings.api_key and self.settings.base_url else None,
            dismissed=self.stop_dismissed_work,
        )

    def stop_dismissed_work(self, work: WorkThread) -> None:
        """The committed user dismissal owns cancellation of only its research."""
        for run in self.canvas.read().runs:
            if run.work_id == work.id:
                self.agent.command(ControlTask(run.task_id, Control.CANCEL))

    def canvas_recovery(self, run: CanvasRun) -> Callable[[object], None]:
        def recover(_root: object) -> None:
            self.continue_thread(run)

        return recover

    def start_background(self) -> None:
        self.startup.start()
        if os.environ.get("WORKSPACE_DESKTOP", "on").lower() != "off":
            # Prepare Qt controls while starting the desktop, so the first
            # canvas click reuses the current native scene and font resources.
            work = self.ui.work(self.work_command, on_problem=self.problem, reveal=False)
            work.publish(replace(self.agent.snapshot(), personal=self.personal.snapshot()))
            work.prepare()
            self.ui.desktop(
                show_agent=self.agent.show,
                show_work=self.show_work,
                stop=self.stop_requested,
                overlay=self.toggle_overlay,
                menu=self.request_menu,
                on_problem=self.problem,
                audio_level=self.desktop.mic.level,
                tiling=self.tile_from_menu,
            )

    def run(self) -> None:
        self.capture_timer = control_policy.initialize_controls(self.window.handle, self.start_background, self.startup_effects)
        self.timings.mark("workers and readiness")
        if self.settings.api_key:
            threading.Thread(target=self.agent.prepare, name="agent panel warmup", daemon=True).start()
        system.run_message_loop()

    def quit(self) -> None:
        timings = Timings("shutdown")
        if self.capture_timer is not None:
            system.kill_window_timer(self.window.handle, self.capture_timer)
            self.capture_timer = None
        self.assistant.stop_capture(discard=True, reason="shutdown")
        timings.mark("stop capture")
        self.personal.close()
        timings.mark("personal work")
        self.triage.close()
        timings.mark("feed triage")
        self.consoles.close()
        timings.mark("console bridge")
        self.communications.close()
        timings.mark("Teams worker")
        self.monitor_layout.close()
        timings.mark("monitor layout")
        try:
            self.ui.close_desktop()
        except OSError as error:
            log(str(error))
        try:
            self.meetings.close()
        except OSError as error:
            log(str(error))
        self.followups.close()
        self.followups.wait_closed()
        self.agent.close()
        if not self.agent.wait_closed(timeout=5):
            log("The work frontend did not finish closing before assistant shutdown.")
        timings.mark("meetings and work frontend")
        self.activity.close()
        self.ui.close_agent()
        self.ui.close_work()
        self.ui.close()
        timings.mark("Qt shutdown")
        self.jobs.put(None)
        self.desktop.mic.close()
        try:
            self.tiling.close()
        except OSError as error:
            log(str(error))
        self.tray.remove()
        self.window.destroy()
        system.close_event(self.mic_event)
        timings.mark("microphone and tiling cleanup")
        system.post_quit()

    def tile_from_menu(self, tool: Tool, hwnd: int) -> None:
        if tool is Tool.WINDOW_SWITCHER:
            self.switch_windows()
            return
        if tool is Tool.COPY_TRANSCRIPT:
            self.assistant.handle(tool, down=True)
            return
        if tool is Tool.TILE_BALANCE:
            threading.Thread(target=self.monitor_layout.balance, name="window redistribution", daemon=True).start()
            return

        def arrange() -> None:
            try:
                self.desktop.arrange(tool, target=hwnd)
            except OSError as error:
                self.problem(str(error))

        self.jobs.put(arrange)

    def switch_windows(self) -> None:
        def focus(handle: int) -> None:
            def activate() -> None:
                try:
                    if self.tiling.focus(handle):
                        return
                except OSError:
                    pass
                if not windows.focus(handle):
                    self.problem("That window is no longer available or Windows refused to focus it.")

            threading.Thread(target=activate, name="window navigation", daemon=True).start()

        def collect() -> None:
            try:
                managed = self.tiling.managed_handles()
            except OSError:
                managed = frozenset[int]()
            visible = frozenset(w.handle for w in windows.windows())
            all_windows = tuple(w for w in windows.windows(include_cloaked=True) if windows.process_id(w.handle) != os.getpid())
            self.ui.switch_windows(switcher_windows(all_windows, visible, managed), focus)

        threading.Thread(target=collect, name="window list", daemon=True).start()

    def stop_requested(self) -> None:
        system.post_message(self.window.handle, WM_REQUEST, Tool.STOP.value, 1)

    def work(self) -> None:
        """The worker thread: slow jobs, one at a time."""
        while (job := self.jobs.get()) is not None:
            try:
                job()
            except Exception:
                log(traceback.format_exc())
                self.problem("Something went wrong; it's in the assistant's log.")

    def record(self, feature: str, details: Mapping[str, Detail]) -> None:
        with contextlib.suppress(OSError):
            usage.record("assistant", feature, details)

    # ---- what the user sees ------------------------------------------------------------

    def show(self, state: State) -> None:
        if self.assistant.listening is not None:
            state = State.LISTENING
        if state in (State.READY, State.LAYOUT_OFF) and self.agent.running():
            state = State.NEEDS_INPUT if self.agent.window is not None and self.agent.window.waiting else State.AGENT
        self.ui.desktop_state(state, agent_speaking=self.assistant.listening is Tool.AGENT_VOICE)
        self.tray.show(State.RECORDING if self.meetings.snapshot().capturing else state)

    def recording_changed(self, state: RecordingState) -> None:
        self.ui.desktop_recording(state)
        self.agent.prepare()
        if self.agent.window is not None:
            self.agent.window.recording(state)
        prior, self._recording_phase = self._recording_phase, state.phase
        failed_capture = prior in ("starting", "recording", "stopping") and state.phase == "finishing" and bool(state.detail)
        if (prior != state.phase and state.phase in ("paused", "interrupted")) or failed_capture:
            self.tray.notify("Meeting transcript", state.detail or "Recording was interrupted. Open Transcripts for the saved part.", warning=True)
        self.show(State.LISTENING if self.assistant.listening is not None else State.READY if self.assistant.layout_on else State.LAYOUT_OFF)

    def recording_action(self, action: RecordingAction) -> None:
        try:
            match action:
                case "start" | "start_microphone":
                    self.meetings.start("both" if action == "start" else "microphone")
                    self.agent.prepare()
                    if self.agent.window is not None:
                        self.agent.window.show()
                case "stop":
                    self.meetings.stop()
                case "retry":
                    self.meetings.retry()
                case "open" | "folder":
                    self.meetings.root.mkdir(parents=True, exist_ok=True)
                    transcript = self.meetings.snapshot().path
                    path = Path(transcript) if action == "open" and transcript else self.meetings.root
                    os.startfile(path if path.exists() else self.meetings.root)
        except (OSError, ValueError) as error:
            self.problem(str(error))

    def refresh_work(self) -> None:
        self.agent.refresh()
        self.followups.refresh()

    def review_feed(self, batch: tuple[Candidate, ...], rules: tuple[str, ...]) -> str:
        research = Research(self.settings, self.triage.research_context, self.triage.research_conversation, stop=self.triage.closed)
        return classify(self.settings, batch, rules, working_context=self.triage.working_context(batch), research=research)

    def work_changed(self, snapshot: WorkSnapshot) -> None:
        self.ui.work(self.work_command, on_problem=self.problem, reveal=False).publish(replace(snapshot, personal=self.personal.snapshot()))
        self.ui.observe_canvas_work(snapshot)
        self.triage.context_changed(snapshot.tasks, snapshot.context)

    def personal_changed(self, view: PersonalView) -> None:
        self.ui.work(self.work_command, on_problem=self.problem, reveal=False).publish(replace(self.agent.snapshot(), personal=view))
        self.ui.observe_canvas(view.catalog)

    def continue_thread(self, run: CanvasRun) -> None:
        self.agent.watch(tuple(binding.task_id for binding in self.canvas.read().runs), owner="canvas")
        match run.intent:
            case CanvasInstruction():
                self.agent.submit_identified(run.task_id, instruction_prompt(run))
                return
            case _:
                pass
        title = next((work.definition.title for work in self.personal.snapshot().catalog.works if work.id == run.work_id), run.work_id)
        self.agent.submit_identified(
            run.task_id,
            f"Research and build the canvas for {title}.\n"
            f"Continue work thread {run.work_id} on the local desktop canvas. Read work_canvas_read and its current "
            "work_items_list representation and linked sources. Inspect relevant browser conversations and their document references; "
            "use outlook_web_documents and outlook_web_open_document for rendered attachments. Find referenced documents in "
            "browser resources or local files, register their verified references with work_items_add_document, compare version evidence, "
            "and use work_canvas_update to collect/nest the sources and useful findings under this work. Arrange with the shared layout. "
            "Research the next useful step and update the work thread with what you learn. Routine collection stays quiet. "
            "Ask the user for clarification when missing input prevents progress; continue this same work after the answer. "
            "Keep your progress and findings on the work representation.",
        )

    def work_command(self, command: WorkCommand) -> None:
        match command:
            case AddDocument() | AddWebPage() | DismissWork() | RestoreWork() | SaveWork() | UnlinkWork():
                validated = PERSONAL_REQUEST.validate_json(PERSONAL_REQUEST.dump_json(command))
                match validated:
                    case AddDocument() | AddWebPage() | DismissWork() | RestoreWork() | SaveWork() | UnlinkWork():
                        self.personal.enqueue(validated)
                    case _:
                        raise ValueError("Invalid personal work edit.")
            case RefreshPersonalWork.REFRESH:
                self.personal.refresh()
            case OpenWorkSource(source_id):
                source = next((source for source in self.personal.snapshot().catalog.sources if source.id == source_id), None)
                if source is None:
                    raise ValueError("This source is no longer available. Refresh My work.")
                if source.kind in (SourceKind.DOCUMENT, SourceKind.WEB_PAGE):
                    self.ui.open_reference(source.url)
                    return
                self.agent.start(
                    f"Open in {source.kind.value.capitalize()}: {source.title}\n"
                    f"Show this exact original source in the user's browser. Application: {source.kind.value}; "
                    f"source identity: {source.identity}; observed URL: {source.url}. "
                    "Use browser_tabs to find the signed-in page and the dedicated app tools to select its exact identity, "
                    "then show the page. If it isn't rendered, search or navigate using its observed title/URL and verify "
                    "the identity before opening. Preserve existing drafts. This request only opens the source."
                )
            case _:
                self.agent.command(command)

    def show_work(self) -> None:
        self.ui.work(self.work_command, on_problem=self.problem)
        self.agent.refresh()

    def show_meetings(self) -> None:
        self.show_work()
        self.ui.show_meetings()
        self.followups.refresh()

    def open_meeting_file(self, path: Path) -> None:
        self.jobs.put(control_policy.meeting_file_job(path, os.startfile, self.problem))

    def meeting_command(self, command: StartMeeting | MeetingCommand) -> MeetingSucceeded | MeetingFailed:
        """Execute the worker's validated request with the existing capture owner."""
        try:
            match command:
                case StartMeeting(source, title):
                    self.meetings.start(source, title)
                case MeetingCommand.STOP:
                    self.meetings.stop()
                case MeetingCommand.RETRY:
                    self.meetings.retry()
                case MeetingCommand.LIST:
                    return MeetingSucceeded(self.meetings.recent())
                case MeetingCommand.STATUS:
                    pass
                case _:
                    assert_never(command)
            return MeetingSucceeded(self.meetings.describe())
        except (OSError, ValueError) as error:
            return MeetingFailed(str(error))

    def agent_done(self) -> None:
        if self.assistant.listening is None:
            self.assistant.idle()

    def voice_agent(self, text: str) -> None:
        self.ui.voice_agent(text, self.agent.voice)

    def problem(self, message: str) -> None:
        log(message)
        system.beep(system.MB_ICONEXCLAMATION)
        self.tray.notify("Workspace", message, warning=True)

    def show_overlay(self, work: Rect) -> None:
        self.ui.show_keyboard_overlay(self.overlay.layer, self.overlay.title, work, visible=self.overlay.visible, pressed=self.overlay.pressed)

    def display_overlay(self, change: control_policy.OverlayChange) -> None:
        self.overlay = replace(self.overlay, enabled=change.enabled)
        self.show_overlay(indicator_area())

    def persist_overlay(self, change: control_policy.OverlayChange) -> None:
        save_enabled(enabled=change.enabled)

    def toggle_overlay(self) -> None:
        change = control_policy.OverlayChange(enabled=not self.overlay.enabled)
        if (problem := control_policy.change_overlay(change, self)) is not None:
            self.problem(problem)

    # ---- messages ----------------------------------------------------------------------

    def layout_changed(self, value: int) -> None:
        with contextlib.suppress(ValueError):
            self.layout = LayoutState(value)
        work = indicator_area()
        if self.layout is not LayoutState.QUIT:
            self.ui.flash("Layout on" if self.layout is LayoutState.ON else "Layout off", work)
        self.assistant.layout_on = self.layout is LayoutState.ON
        if not self.assistant.layout_on:
            self.assistant.stop_capture(reason="layout_off")
        self.ui.desktop_layout(enabled=self.assistant.layout_on)
        self.overlay = self.overlay.set_layout(on=self.assistant.layout_on)
        self.ui.show_pressed_keys(self.overlay.pressed, reset=True)
        self.show_overlay(work)
        if self.assistant.listening is None:
            self.assistant.idle()

    def on_message(self, hwnd: int, message: int, wparam: int, lparam: int) -> int | None:
        try:
            if message == system.WM_TIMER and wparam == self.capture_timer:
                self.assistant.expire_capture(time.monotonic())
                return 0
            if message == WM_SHOW_MENU:
                self.menu()
                return 0
            if message in (WM_KEY_STATE, WM_REQUEST):
                action = control_policy.control_event(control_policy.WindowInput(message, wparam, lparam), APPS)
                match action:
                    case control_policy.PhysicalKey(scancode=scancode, down=down):
                        self.overlay = self.overlay.key(scancode, down=down)
                        self.ui.show_pressed_keys(self.overlay.pressed, reset=action.reset)
                    case control_policy.Action.OPEN_INBOX:
                        self.ui.open_inbox(self.agent.show)
                    case control_policy.Action.SWITCH_WINDOWS:
                        self.switch_windows()
                    case control_policy.Action.TOGGLE_MEETING:
                        self.recording_action("stop" if self.meetings.snapshot().capturing else "start")
                    case control_policy.Action.BALANCE_WINDOWS:
                        self.tile_from_menu(Tool.TILE_BALANCE, 0)
                    case control_policy.FeatureRequest(request=request, down=down):
                        self.assistant.handle(request, down=down)
                    case None:
                        pass
                    case _:
                        assert_never(action)
                return 0
            if message == WM_INDICATOR:
                index, locked, caps_word = decode_indicator(wparam)
                layer = next((layer for layer in Layer if layer.value == index), None)
                work = indicator_area()
                self.ui.indicate(indicator_text(layer, locked=locked, caps_word=caps_word), work)
                self.overlay = self.overlay.indicate(layer, locked=locked, caps_word=caps_word)
                self.show_overlay(work)
                return 0
            if message == WM_LAYOUT_STATE:
                self.layout_changed(wparam)
                return 0
            if message == system.WM_CLOSE:  # the keeper asks: it's restarting or installing
                self.quit()
                return 0
            if message == WM_TRAY and lparam in (system.WM_LBUTTONUP, system.WM_RBUTTONUP):
                self.menu()
                return 0
        except Exception:
            log(traceback.format_exc())
        return None

    def request_menu(self) -> None:
        system.post_message(self.window.handle, WM_SHOW_MENU, 0, 0)

    def menu(self) -> None:
        state = control_policy.MenuState(
            layout=self.layout, overlay_enabled=self.overlay.enabled, agent_running=self.agent.running(), capturing=self.meetings.snapshot().capturing
        )
        items = control_policy.menu_items(state)
        match shell.show_menu(self.window.handle, items):
            case control_policy.Menu.TOGGLE_LAYOUT.value:
                if not control_policy.toggle_layout(self.startup_effects):
                    self.problem("Couldn't reach the layout. Try Start layout or Restart layout.")
            case control_policy.Menu.RESTART_LAYOUT.value:
                keeper.ask("restart_layout")
            case control_policy.Menu.RESTART_ASSISTANT.value:
                keeper.ask("restart_assistant")
            case control_policy.Menu.RESTART_AUTOMATION.value:
                keeper.ask("restart_automation")
            case control_policy.Menu.OVERLAY.value:
                self.toggle_overlay()
            case control_policy.Menu.KEYMAP.value:
                self.ui.show_keymap()
            case control_policy.Menu.ASK.value:
                self.assistant.handle(Tool.ASK, down=True)
            case control_policy.Menu.AGENT.value:
                self.assistant.handle(Tool.AGENT_TYPED, down=True)
            case control_policy.Menu.WORK.value:
                self.show_work()
            case control_policy.Menu.TASKBAR.value:
                self.ui.toggle_taskbar()
            case control_policy.Menu.STOP_AGENT.value:
                self.agent.stop()
            case control_policy.Menu.MEETING.value:
                self.recording_action("stop" if self.meetings.snapshot().capturing else "start")
            case control_policy.Menu.TRANSCRIPTS.value:
                self.recording_action("folder")
            case control_policy.Menu.FOLLOWUPS.value:
                self.show_meetings()
            case control_policy.Menu.UNDO.value:
                keeper.ask("undo")
            case control_policy.Menu.USAGE.value:
                os.startfile(write_report())
            case control_policy.Menu.LOGS.value:
                DIRECTORY.mkdir(parents=True, exist_ok=True)
                os.startfile(DIRECTORY)
            case control_policy.Menu.QUIT.value:
                self.quit()
            case _:
                pass


class Controller(Protocol):
    def run(self) -> None: ...


def create_ui() -> Ui:
    # Resolve the lazy Qt module only after physical-pixel initialization.
    return Ui()


def create_controller(settings: Settings | Missing, ui: Ui) -> Controller:
    return AssistantApp(settings, ui)


@dataclass(frozen=True, slots=True)
class Runtime:
    """The identity and factories of one owned native/Qt process lifetime.

    Factories are invoked on their required threads; the native window title
    identifies the same controller when Qt exits before its message loop.
    """

    title: str = ASSISTANT_WINDOW
    lock_name: str = LOCK_NAME
    ui: Callable[[], Ui] = create_ui
    controller: Callable[[Settings | Missing, Ui], Controller] = create_controller


def run(settings: Settings | Missing, *, timings: Timings | None = None, runtime: Runtime | None = None) -> Exit:
    """Blocks until quit from the tray."""
    screen.use_physical_pixels()  # before any window exists
    runtime = Runtime() if runtime is None else runtime
    lock = system.create_lock(runtime.lock_name)
    if lock is None:
        return Exit.ALREADY_RUNNING
    try:
        timings = timings or Timings("startup")
        ui = runtime.ui()
        timings.mark("Qt initialization")
        errors: queue.Queue[BaseException] = queue.Queue()

        def control() -> None:
            try:
                runtime.controller(settings, ui).run()
            except BaseException as error:
                errors.put(error)
            finally:
                try:
                    ui.close()
                except BaseException as error:
                    errors.put(error)

        controller = threading.Thread(target=control, name="assistant control", daemon=True)
        controller.start()
        try:
            ui.run()
        finally:
            if controller.is_alive() and (window := windows.find(runtime.title)) is not None:
                system.post_message(window, system.WM_CLOSE, 0, 0)
            controller.join(timeout=10)
        if controller.is_alive():
            raise OSError("The assistant control thread did not finish closing.")
        if not errors.empty():
            raise errors.get_nowait()
        return Exit.QUIT
    finally:
        system.release_lock(lock)


def show_error(message: str) -> None:
    system.message_box(message, "Workspace", system.MB_ICONHAND)
