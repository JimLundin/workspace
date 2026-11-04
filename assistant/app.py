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

import components
import keeper
import keeper_control
import usage
from assistant.activity import ActivityTracker
from automation.activity import ContextSnapshot, Observation, Policy
from config import APPS
from usage import DIRECTORY, Detail
lazy from assistant import control_policy
lazy from assistant.automatic_meetings import AutomaticAttention, AutomaticMeetings
lazy from assistant.browser import Browser
lazy from assistant.browser_session import Product
lazy from assistant.canvas_activity import CanvasInstruction, CanvasRun
lazy from assistant.communications_browser import TeamsWeb
lazy from assistant.communications_service import Communications
lazy from assistant.communications_state import COMMUNICATIONS_STATE
lazy from assistant.desktop import WinDesktop
lazy from assistant.features import Assistant
lazy from assistant.feed_contracts import STORED_BOARD
lazy from assistant.feed_research import Research
lazy from assistant.feed_sources import Candidate
lazy from assistant.feed_triage_service import Triage, classify
lazy from assistant.feed_work import FeedWork
lazy from assistant.lifecycle import Timings
lazy from assistant.llm import MAX_SECONDS, Missing, Settings
lazy from assistant.meeting_browser import TeamsCalls
lazy from assistant.meeting_detection import PREFERENCE, AutomaticStatus
lazy from assistant.meeting_store import MeetingArchive, MeetingStore
lazy from assistant.meetings import Meetings
lazy from assistant.notification_sources import NOTIFICATION_STATE
lazy from assistant.personal_work_model import Correlator
lazy from assistant.personal_work_service import PersonalWork
lazy from assistant.personal_work_sources import BrowserSources
lazy from assistant.personal_work_store import PersonalStore
lazy from assistant.personal_work_tools import source_request
lazy from assistant.recording_state import RecordingAction, RecordingState
lazy from assistant.report import write_report
lazy from assistant.state_store import windows_store
lazy from assistant.work_agent import WorkAgent
lazy from assistant.work_bridge import WorkOwners, answer
lazy from assistant.work_canvas import WorkCanvas, run_prompt
lazy from assistant.work_commands import ControlTask, WorkViewCommand
lazy from assistant.work_snapshot import WorkSnapshot
lazy from automation import ipc
lazy from automation.bridge import BridgeClient
lazy from automation.context import ContextStore
lazy from automation.ipc import MeetingCommand, StartMeeting
lazy from automation.personal_work import (
    AddDocument,
    AddWebPage,
    DismissWork,
    MeetingSource,
    OpenWorkSource,
    PersonalView,
    RefreshPersonalWork,
    RestoreWork,
    SaveWork,
    SourceKind,
    UnlinkWork,
    WorkThread,
)
lazy from automation.store import TaskStore
lazy from automation.task import Control, RequestKind
lazy from automation.work_folder import BROWSER_PROFILE, WORK
lazy from desktop_ui.icons import State
lazy from desktop_ui.keymap import indicator_text
lazy from desktop_ui.navigation import Source, SwitcherPick
lazy from desktop_ui.overlay import OverlayState, load_enabled, save_enabled
lazy from desktop_ui.tray import Tray
lazy from desktop_ui.ui import Ui
lazy from miryoku.layout import Layer
lazy from protocol import WM_CHORD, WM_INDICATOR, WM_KEY_STATE, WM_LAYOUT_STATE, WM_REQUEST, LayoutState, Tool, decode_indicator
lazy from winapi import audio, recording, screen, shell, system, windows
lazy from winapi.pcm import RATE
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


def configured(settings: Settings | Missing) -> tuple[Settings, Missing | None]:
    """The settings the app runs with and, when credentials are absent, what is missing."""
    match settings:
        case Missing():
            return Settings("", "", "", "", ""), settings
        case Settings():
            return settings, None


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
        components.ready()


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
        "automatic_attention",
        "automatic_meetings",
        "canvas",
        "capture_timer",
        "communications",
        "desktop",
        "jobs",
        "layout",
        "meetings",
        "mic_event",
        "overlay",
        "personal",
        "settings",
        "startup",
        "startup_effects",
        "timings",
        "tray",
        "triage",
        "ui",
        "window",
        "work_owners",
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
            on_show_agent=self.show_agent,
        )
        self.overlay = OverlayState(enabled=load_enabled())
        self.ui.desktop_overlay(enabled=self.overlay.enabled)
        self.jobs: queue.Queue[Callable[[], None] | None] = queue.Queue()
        self.window = shell.AppWindow(components.ASSISTANT.window.title, self.on_message)
        self.tray = Tray(self.window.handle, WM_TRAY)
        self.automatic_attention = AutomaticAttention(self.ui.desktop_automatic, self.warn_automatic_recording)
        self.mic_event = system.create_event()
        mic = audio.Microphone(RATE, MAX_SECONDS, self.mic_event)
        self.desktop = WinDesktop(self.window.handle, mic, self.ui, on_state=self.show, on_notify=self.tray.notify, on_problem=self.problem)
        self.timings.mark("control window and microphone")
        self.settings, missing = configured(settings)
        self.activity: ActivityTracker

        def context() -> ContextSnapshot:
            # The tracker and runner refer to each other; observe after composition.
            return self.activity.snapshot()

        tasks = TaskStore(WORK.journal)
        saved_context = ContextStore(tasks.path)
        self.agent = WorkAgent(
            tasks,
            saved_context,
            BridgeClient(WORK.root),
            lambda runner: self.ui.agent(
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
            owners=self.owner_command,
        )
        self.timings.mark("work frontend")
        self.activity = ActivityTracker(
            foreground_context,
            self.agent.running,
            policy=Policy(enabled=os.environ.get("WORKSPACE_AGENT_CONTEXT", "recent").lower() != "off"),
        )
        self.communications = Communications(
            TeamsWeb(BROWSER_PROFILE),
            windows_store(DIRECTORY / "communications.bin", COMMUNICATIONS_STATE),
            self.ui.communications_changed,
        )
        self.canvas: WorkCanvas = WorkCanvas(
            WORK.root / "canvas.sqlite3",
            self.continue_thread,
            self.ui.publish_canvas,
            autonomous=bool(self.settings.api_key and self.settings.base_url),
        )
        self.personal = self.create_personal(tasks)
        self.recover_canvas(tasks)
        self.triage = self.create_feed(FeedWork(tasks, saved_context, context))
        self.work_owners = WorkOwners(self.triage.command, self.personal.handle, self.canvas.command)
        self.ui.configure_feed(windows_store(DIRECTORY / "notifications.bin", NOTIFICATION_STATE), self.triage.observe)
        self.timings.mark("communications and desktop owners")
        archive = MeetingArchive(DIRECTORY / "meetings")
        self.ui.configure_meetings(archive, self.open_meeting_file)
        self.meetings = Meetings(
            self.settings,
            lambda source: recording.MeetingAudio(computer_audio=source == "both"),
            archive=archive,
            on_update=self.recording_changed,
            on_meeting=self.observe_meeting,
        )
        self.automatic_meetings = AutomaticMeetings(
            self.meetings,
            TeamsCalls(Browser(BROWSER_PROFILE, source=Product.EDGE)),
            windows_store(DIRECTORY / "automatic-meetings.bin", PREFERENCE),
            publish=self.automatic_recording_changed,
        )
        self.timings.mark("meeting services")
        self.assistant = Assistant(
            self.desktop,
            self.settings,
            record=self.record,
            submit=self.jobs.put,
            controls=self,
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
                self.meetings.start_worker,
                self.automatic_meetings.start,
            )
        )
        if missing is not None:
            self.tray.notify("Workspace", f"The AI tools need {', '.join(missing.names)}; the layout works without them.", warning=True)

    # ---- running -----------------------------------------------------------------------

    def observe_meeting(self, store: MeetingStore) -> None:
        """Canvas intake failures must not fail a recording or its transcription."""
        try:
            self.personal.observe_meeting(store)
        except Exception as error:
            log(f"Meeting canvas intake failed: {error}. The journal is saved; startup will retry intake.")

    def create_personal(self, tasks: TaskStore) -> PersonalWork:
        self.ui.configure_work(self.work_command, on_problem=self.problem)
        self.ui.configure_canvas(self.canvas, self.agent.notify_canvas, observe_session=self.canvas.observe_session)
        self.agent.watch(tuple(run.task_id for run in self.canvas.read().runs), owner="canvas")
        return PersonalWork(
            PersonalStore(tasks.path),
            BrowserSources(Browser(BROWSER_PROFILE, source=Product.EDGE)),
            self.personal_changed,
            model=Correlator(self.settings) if self.settings.api_key and self.settings.base_url else None,
            dismissed=self.stop_dismissed_work,
        )

    def recover_canvas(self, tasks: TaskStore) -> None:
        """Queue restored runs only after their personal-work title owner exists."""
        if self.settings.api_key and self.settings.base_url:
            # Recover only the crash window between binding and task commit.
            # Existing task prompts may have been redirected by the user.
            for run in self.canvas.read().runs:
                match run:
                    case CanvasRun(intent=CanvasInstruction()) | CanvasRun(evidence=str()) if tasks.get(run.task_id) is None:
                        self.continue_thread(run)
                    case _:
                        pass

    def create_feed(self, work: FeedWork) -> Triage:
        """Construct the feed owner over the durable task/context observations."""
        return Triage(
            windows_store(DIRECTORY / "work-feed.bin", STORED_BOARD),
            self.review_feed,
            submit=self.agent.submit_identified,
            work=work,
            personal=self.personal,
        )

    def stop_dismissed_work(self, work: WorkThread) -> None:
        """The committed user dismissal owns cancellation of only its research."""
        for run in self.canvas.read().runs:
            if run.work_id == work.id:
                self.agent.command(ControlTask(run.task_id, Control.CANCEL))

    def start_background(self) -> None:
        self.startup.start()
        if os.environ.get("WORKSPACE_DESKTOP", "on").lower() != "off":
            # Prepare Qt controls while starting the desktop, so the first
            # canvas click reuses the current native scene and font resources.
            work = self.ui.work_window()
            work.publish(replace(self.agent.snapshot(), personal=self.personal.snapshot()))
            work.prepare()
            self.ui.desktop(
                show_agent=self.agent.show,
                show_work=self.show_work,
                stop=lambda: self.choose_tool(Tool.STOP, 0),
                overlay=self.toggle_overlay,
                menu=self.request_menu,
                on_problem=self.problem,
                audio_level=self.desktop.mic.level,
                tool=self.choose_tool,
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
        self.agent.close()
        # A canvas call waits up to eight seconds on Qt. Retain every desktop
        # owner until the dispatcher and observer have drained their replies.
        if not self.agent.wait_closed(timeout=12):
            raise RuntimeError("The work frontend did not release its desktop owner calls before shutdown.")
        timings.mark("work frontend and desktop calls")
        self.personal.close()
        timings.mark("personal work")
        self.triage.close()
        timings.mark("feed triage")
        self.communications.close()
        timings.mark("Teams worker")
        self.automatic_meetings.close()
        try:
            self.ui.close_desktop()
        except OSError as error:
            log(str(error))
        try:
            self.meetings.close()
        except OSError as error:
            log(str(error))
        timings.mark("meetings and work frontend")
        self.activity.close()
        self.ui.close_windows()
        self.ui.close()
        timings.mark("Qt shutdown")
        self.jobs.put(None)
        self.desktop.close_microphone()
        self.tray.remove()
        self.window.destroy()
        system.close_event(self.mic_event)
        timings.mark("microphone cleanup")
        system.post_quit()

    def choose_tool(self, tool: Tool, target: int) -> None:
        """Marshal menu choices from Qt to the assistant's control-thread owner."""
        system.post_message(self.window.handle, control_policy.WM_TOOL_CHOSEN, tool.value, target)

    def open_inbox(self) -> None:
        self.ui.open_inbox()

    def show_agent(self) -> None:
        self.agent.show()

    def stop_agent(self) -> None:
        self.agent.stop()

    def toggle_meeting(self) -> None:
        self.recording_action("stop" if self.meetings.snapshot().capturing else "start")

    def switch_windows(self) -> None:
        def focus(handle: int) -> None:
            self.ui.navigate(SwitcherPick(handle, Source.KEY))

        def collect() -> None:
            own = os.getpid()
            self.ui.switch_windows(tuple(w for w in windows.windows() if windows.process_id(w.handle) != own), focus)

        threading.Thread(target=collect, name="window list", daemon=True).start()

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
                    self.automatic_meetings.start_recording("both" if action == "start" else "microphone")
                    self.agent.prepare()
                    if self.agent.window is not None:
                        self.agent.window.show()
                case "stop":
                    self.automatic_meetings.stop_recording()
                case "automatic":
                    self.automatic_meetings.toggle()
                case "retry":
                    self.meetings.retry()
                case "open" | "folder":
                    self.meetings.root.mkdir(parents=True, exist_ok=True)
                    transcript = self.meetings.snapshot().path
                    path = Path(transcript) if action == "open" and transcript else self.meetings.root
                    os.startfile(path if path.exists() else self.meetings.root)
        except (OSError, ValueError) as error:
            self.problem(str(error))

    def automatic_recording_changed(self, status: AutomaticStatus) -> None:
        self.automatic_attention.changed(status)

    def warn_automatic_recording(self) -> None:
        self.tray.notify(
            "Automatic Teams recording",
            "Meeting detection is unavailable. Check the browser connection or choose Record a meeting manually.",
            warning=True,
        )

    def review_feed(self, batch: tuple[Candidate, ...], rules: tuple[str, ...]) -> str:
        research = Research(self.settings, self.triage.research_context, self.triage.research_conversation, stop=self.triage.closed)
        return classify(self.settings, batch, rules, working_context=self.triage.working_context(batch), research=research)

    def work_changed(self, snapshot: WorkSnapshot) -> None:
        self.canvas.observe_work(snapshot)
        self.triage.context_changed(snapshot.tasks, snapshot.context)
        self.ui.work_window().publish(replace(snapshot, personal=self.personal.snapshot()))

    def personal_changed(self, view: PersonalView) -> None:
        self.canvas.observe_catalog(view.catalog)
        self.ui.work_window().publish(replace(self.agent.snapshot(), personal=view))

    def continue_thread(self, run: CanvasRun) -> None:
        self.agent.watch(tuple(binding.task_id for binding in self.canvas.read().runs), owner="canvas")
        title = self.canvas.title(run.work_id)
        self.agent.submit_identified(run.task_id, run_prompt(run, title), RequestKind.GENERAL)

    def work_command(self, command: WorkViewCommand) -> None:
        match command:
            case AddDocument() | AddWebPage() | DismissWork() | RestoreWork() | SaveWork() | UnlinkWork():
                self.personal.enqueue(command)
            case RefreshPersonalWork.REFRESH:
                self.personal.refresh()
            case OpenWorkSource(source_id):
                source = next((source for source in self.personal.snapshot().catalog.sources if source.id == source_id), None)
                if source is None:
                    raise ValueError("This source is no longer available. Refresh My work.")
                if isinstance(source, MeetingSource):
                    self.open_meeting_file(Path(source.meeting.transcript_path))
                    return
                if source.kind in (SourceKind.DOCUMENT, SourceKind.WEB_PAGE):
                    self.ui.open_reference(source.url)
                    return
                self.agent.start(source_request(source))
            case _:
                self.agent.command(command)

    def show_work(self) -> None:
        self.ui.work_window().show()
        self.agent.refresh()

    def open_meeting_file(self, path: Path) -> None:
        self.jobs.put(control_policy.meeting_file_job(path, os.startfile, self.problem))

    def owner_command(self, call: ipc.OwnerCall) -> ipc.OwnerResult:
        """Route the work process's one owner-call seam to its desktop owners."""
        return answer(call, self.work_owners, self.meeting_command)

    def meeting_command(self, command: StartMeeting | MeetingCommand) -> ipc.Succeeded | ipc.Failed:
        """Execute the worker's validated request with the existing capture owner."""
        try:
            match command:
                case StartMeeting(source, title):
                    self.automatic_meetings.start_recording(source, title)
                case MeetingCommand.STOP:
                    self.automatic_meetings.stop_recording()
                case MeetingCommand.RETRY:
                    self.meetings.retry()
                case MeetingCommand.LIST:
                    return ipc.Succeeded(self.meetings.recent())
                case MeetingCommand.STATUS:
                    pass
                case _:
                    assert_never(command)
            return ipc.Succeeded(self.meetings.describe())
        except (OSError, ValueError) as error:
            return ipc.Failed(str(error))

    def agent_done(self) -> None:
        if self.assistant.listening is None:
            self.assistant.idle()

    def run_agent(self, text: str) -> None:
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
        self.ui.desktop_overlay(enabled=change.enabled)

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
            if message == shell.TASKBAR_CREATED:
                self.tray.restore()
                return 0
            if message == system.WM_TIMER and wparam == self.capture_timer:
                self.assistant.expire_capture(time.monotonic())
                return 0
            if message == WM_SHOW_MENU:
                self.menu()
                return 0
            if message in (WM_KEY_STATE, WM_REQUEST, control_policy.WM_TOOL_CHOSEN):
                action = control_policy.control_event(control_policy.WindowInput(message, wparam, lparam), APPS)
                match action:
                    case control_policy.PhysicalKey(scancode=scancode, down=down):
                        self.overlay = self.overlay.key(scancode, down=down)
                        self.ui.show_pressed_keys(self.overlay.pressed, reset=action.reset)
                    case control_policy.FeatureRequest(request=request, down=down):
                        self.assistant.handle(request, down=down)
                    case control_policy.ChosenTool(tool=tool, target=target):
                        self.assistant.handle(tool, down=True, target=target)
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
            if message == WM_CHORD:
                self.ui.desktop_chord(held=bool(wparam))
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
                keeper_control.ask(keeper.REQUESTS, keeper_control.Restart("layout"))
            case control_policy.Menu.RESTART_ASSISTANT.value:
                keeper_control.ask(keeper.REQUESTS, keeper_control.Restart("assistant"))
            case control_policy.Menu.RESTART_AUTOMATION.value:
                keeper_control.ask(keeper.REQUESTS, keeper_control.Restart("automation"))
            case control_policy.Menu.OVERLAY.value:
                self.toggle_overlay()
            case control_policy.Menu.KEYMAP.value:
                self.ui.show_keymap()
            case control_policy.Menu.AGENT.value:
                self.assistant.handle(Tool.AGENT_TYPED, down=True)
            case control_policy.Menu.WORK.value:
                self.show_work()
            case control_policy.Menu.TASKBAR.value:
                self.ui.toggle_taskbar()
            case control_policy.Menu.STOP_AGENT.value:
                self.agent.stop()
            case control_policy.Menu.MEETING.value:
                self.assistant.handle(Tool.MEETING_TOGGLE, down=True)
            case control_policy.Menu.TRANSCRIPTS.value:
                self.recording_action("folder")
            case control_policy.Menu.UNDO.value:
                keeper_control.ask(keeper.REQUESTS, keeper_control.Undo())
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

    title: str = components.ASSISTANT.window.title
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
