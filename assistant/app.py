"""The assistant: the agent and its work, the canvas document, meetings and the microphone.

It runs without the desktop and the desktop without it. It never touches the
desktop's windows: it sends `contracts.desktop_link` messages through a
`DesktopPort` and takes the desktop's commands from the link. The keyboard
sends it only the requests it owns (dictation, the agent, meetings), to its own
hidden window, and durable work executes on the worker's threads here.
"""

import contextlib
import os
import queue
import sqlite3
import threading
import time
import traceback
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from enum import Enum, auto
from pathlib import Path
from typing import Final, Protocol, assert_never

import components
import usage
from assistant.activity import ActivityTracker
from automation.activity import ContextSnapshot, Observation, Policy
from config import APPS
from usage import DIRECTORY, Detail
lazy import contracts.desktop_link
lazy from assistant import control_policy
lazy from assistant.agent_window import AgentWindow
lazy from assistant.automatic_meetings import AutomaticAttention, AutomaticMeetings
lazy from assistant.browser import Browser
lazy from assistant.browser_session import Product
lazy from assistant.communications_browser import TeamsWeb
lazy from assistant.communications_service import Communications
lazy from assistant.communications_state import COMMUNICATIONS_STATE
lazy from assistant.desktop import WinDesktop
lazy from assistant.desktop_commands import DesktopCommands
lazy from assistant.desktop_port import DesktopPort, LevelFeed, LinkedDesktop, SessionView, ViewThread
lazy from assistant.features import Assistant
lazy from assistant.feed_contracts import STORED_BOARD
lazy from assistant.feed_inbox import FeedInbox
lazy from assistant.feed_research import Research
lazy from assistant.feed_sources import Candidate
lazy from assistant.feed_triage_service import Triage, classify
lazy from assistant.feed_work import FeedWork
lazy from assistant.lifecycle import Timings
lazy from assistant.llm import MAX_SECONDS, Missing, Settings
lazy from assistant.meeting_browser import TeamsCalls
lazy from assistant.meeting_store import MeetingArchive, MeetingStore
lazy from assistant.meeting_tools import MeetingCommand, StartMeeting
lazy from assistant.meetings import Meetings
lazy from assistant.notification_sources import NOTIFICATION_STATE
lazy from assistant.personal_work_model import Correlator
lazy from assistant.personal_work_service import PersonalWork
lazy from assistant.personal_work_sources import BrowserSources
lazy from assistant.personal_work_store import PersonalStore
lazy from assistant.personal_work_tools import source_request
lazy from assistant.state_store import windows_store
lazy from assistant.work_agent import WorkAgent
lazy from assistant.work_bridge import WorkOwners
lazy from assistant.work_canvas import WorkCanvas, run_prompt
lazy from automation.context import ContextStore
lazy from automation.store import TaskStore
lazy from automation.work_folder import BROWSER_PROFILE, WORK
lazy from automation.worker import OwnerCalls, Worker, native_runner, warm_sdk
lazy from contracts.canvas_activity import CanvasInstruction, CanvasRun
lazy from contracts.desktop_link import (
    AutomaticChanged,
    CanvasChanged,
    JobChanged,
    MeetingPage,
    Notify,
    OpenReference,
    RecordingChanged,
    RouteSpeech,
    ShowWork,
    VoiceChanged,
    WorkChanged,
    from_desktop,
)
lazy from contracts.meeting_detection import PREFERENCE, AutomaticStatus
lazy from contracts.personal_work import (
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
lazy from contracts.recording_state import RecordingAction, RecordingState
lazy from contracts.status import Job, State
lazy from contracts.task import Control, RequestKind
lazy from contracts.work_canvas_contracts import CanvasPublication
lazy from contracts.work_commands import ControlTask, ReadMeeting, WorkViewCommand
lazy from contracts.work_snapshot import WorkSnapshot
lazy from link.server import Server
lazy from protocol import WM_LAYOUT_STATE, WM_REQUEST, LayoutState, Tool, decode
lazy from winapi import audio, recording, screen, shell, system, windows
lazy from winapi.pcm import RATE
lazy from winapi.shapes import Window
lazy from winapi.system_notices import Observed

ROOT: Final = Path(__file__).resolve().parent.parent
LOCK_NAME: Final = "Local\\workspace-assistant"
LOG: Final = DIRECTORY / "assistant.log"
WM_LINK: Final = system.WM_APP + 21
"""Link reader -> control thread: commands from the desktop are waiting."""


def log(text: str) -> None:
    """The assistant's own log: problems and crashes (there's no console under pythonw)."""
    with contextlib.suppress(OSError):
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as file:
            file.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {text}\n")


# ---- the request context ---------------------------------------------------------------


def workspace_processes() -> frozenset[int]:
    """This process and the desktop's: either's windows are Workspace's own."""
    desktop = windows.find(components.DESKTOP.window.title)
    return frozenset((os.getpid(), *((windows.process_id(desktop),) if desktop else ())))


def foreground_context() -> Observation:
    """Keep Workspace's own windows from replacing the app a request refers to."""
    handle = windows.foreground()
    if not handle:
        return "unavailable"
    if windows.process_id(handle) in workspace_processes():
        return "workspace"
    return Window(handle, windows.title(handle), windows.exe(handle), minimized=windows.is_minimized(handle))


# ---- the program -----------------------------------------------------------------------


class Exit(Enum):
    QUIT = auto()
    ALREADY_RUNNING = auto()


def configured(settings: Settings | Missing) -> tuple[Settings, Missing | None]:
    """The settings the app runs with and, when credentials are absent, what is missing."""
    match settings:
        case Missing():
            return Settings("", "", "", ""), settings
        case Settings():
            return settings, None


@dataclass(frozen=True, slots=True)
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
        "automation",
        "canvas",
        "capture_timer",
        "commands",
        "commands_handler",
        "communications",
        "desktop",
        "feed",
        "jobs",
        "layout",
        "levels",
        "machine",
        "meetings",
        "mic_event",
        "personal",
        "publication",
        "session",
        "settings",
        "startup",
        "startup_effects",
        "timings",
        "triage",
        "view_thread",
        "window",
        "work_owners",
        "worker",
    )

    def __init__(
        self,
        settings: Settings | Missing,
        desktop: DesktopPort,
        *,
        startup_effects: control_policy.StartupEffects | None = None,
        window: components.Window = components.ASSISTANT.window,
    ) -> None:
        self.startup_effects: control_policy.StartupEffects = NativeStartup() if startup_effects is None else startup_effects
        self.timings = Timings("startup")
        self._recording_phase = "idle"
        self.desktop = desktop
        self.jobs: queue.Queue[Callable[[], None] | None] = queue.Queue()
        self.commands: queue.Queue[bytes] = queue.Queue()
        self.publication: CanvasPublication | None = None
        self.session: AgentWindow | None = None
        """The agent session, once the work frontend has asked for it."""
        self.window = shell.AppWindow(window.title, self.on_message)
        self.view_thread = ViewThread()
        self.automatic_attention = AutomaticAttention(lambda status: self.desktop.send(AutomaticChanged(status)), self.warn_automatic_recording)
        self.mic_event = system.create_event()
        mic = audio.Microphone(RATE, MAX_SECONDS, self.mic_event)
        self.machine = WinDesktop.following(
            self.window.handle, mic, on_state=self.show, on_job=self.job_changed, on_notify=self.notify, on_problem=self.problem
        )
        self.levels = LevelFeed(mic.level, desktop)
        self.timings.mark("control window and microphone")
        self.settings, missing = configured(settings)
        self.activity: ActivityTracker

        def context() -> ContextSnapshot:
            # The tracker and runner refer to each other; observe after composition.
            return self.activity.snapshot()

        tasks = TaskStore(WORK.journal)
        saved_context = ContextStore(tasks.path)
        self.automation = Worker(tasks, WORK.root)
        self.agent = WorkAgent(
            tasks,
            saved_context,
            self.automation,
            self.session_window,
            on_snapshot=self.work_changed,
            on_done=self.agent_done,
            report_error=log,
            on_start=lambda: self.show(State.AGENT),
            context=context,
        )
        self.timings.mark("work frontend")
        self.activity = ActivityTracker(
            foreground_context,
            self.agent.running,
            policy=Policy(enabled=os.environ.get("WORKSPACE_AGENT_CONTEXT", "recent").lower() != "off"),
        )
        self.canvas: WorkCanvas = WorkCanvas(
            WORK.root / "canvas.sqlite3",
            self.continue_thread,
            self.canvas_published,
            autonomous=bool(self.settings.api_key and self.settings.base_url),
        )
        self.personal = self.create_personal(tasks)
        self.recover_canvas(tasks)
        self.triage = self.create_feed(FeedWork(tasks, saved_context, context))
        self.feed = FeedInbox(windows_store(DIRECTORY / "notifications.bin", NOTIFICATION_STATE), self.triage.observe)
        self.communications = Communications(
            TeamsWeb(BROWSER_PROFILE), windows_store(DIRECTORY / "communications.bin", COMMUNICATIONS_STATE), self.feed.communications
        )
        self.work_owners = WorkOwners(self.triage.command, self.personal.handle, self.canvas.command)
        self.commands_handler = DesktopCommands(self.canvas, desktop, self)
        self.timings.mark("communications and desktop owners")
        archive = MeetingArchive(DIRECTORY / "meetings")
        self.meetings = Meetings(
            self.settings,
            lambda source: recording.MeetingAudio(computer_audio=source == "both"),
            archive=archive,
            on_update=self.recording_changed,
            on_meeting=self.observe_meeting,
            log=log,
        )
        self.automatic_meetings = AutomaticMeetings(
            self.meetings,
            TeamsCalls(Browser(BROWSER_PROFILE, source=Product.EDGE)),
            windows_store(DIRECTORY / "automatic-meetings.bin", PREFERENCE),
            publish=self.automatic_recording_changed,
        )
        self.timings.mark("meeting services")
        self.assistant = Assistant(self.machine, self.settings, record=self.record, submit=self.jobs.put, controls=self, missing=missing)
        self.layout: LayoutState | None = None
        self.capture_timer: int | None = None
        """What the layout last said; None until it does."""
        self.worker = threading.Thread(target=self.work, name="worker", daemon=True)
        self.startup = WorkerStartup(
            (
                lambda: self.start_work(tasks, saved_context),
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
            self.notify("Workspace", f"The AI tools need {', '.join(missing.names)}; the layout works without them.")

    # ---- the agent session's view ------------------------------------------------------

    def session_window(self, runner: WorkAgent) -> AgentWindow:
        """The agent session: its snapshots go to the desktop and the canvas, from one view thread."""
        window = AgentWindow(
            runner.stop,
            post=self.view_thread.post,
            create_view=lambda _: SessionView(self.desktop, self.canvas.observe_session),
            on_problem=self.problem,
            on_reset=runner.new_conversation,
            on_submit=runner.start,
            on_waiting=lambda waiting: self.show(State.NEEDS_INPUT if waiting else State.AGENT),
            on_recording=self.recording_action,
            on_work=self.show_work,
            log=log,
        )
        if self.publication is not None:
            window.canvas_attention(self.publication.attention)
        self.session = window
        return window

    def canvas_published(self, publication: CanvasPublication) -> None:
        """Any thread: the canvas document's owner changed it; the session and the desktop observe it."""
        self.publication = publication
        if self.session is not None:
            self.session.canvas_attention(publication.attention)
        self.desktop.send(CanvasChanged(publication))

    # ---- running -----------------------------------------------------------------------

    def start_work(self, tasks: TaskStore, saved_context: ContextStore) -> None:
        """Recover saved work before readiness; execution then runs on the worker's threads."""
        calls = OwnerCalls(tasks, self.work_owners.handle, self.meeting_command)
        runner, close_background = native_runner(
            self.settings, self.automation, calls, hwnd=self.window.handle, contexts=saved_context, context=self.activity.snapshot
        )
        self.automation.start(runner, self.agent.deliver, close_background)
        if self.settings.api_key:
            threading.Thread(target=warm_sdk, args=(WORK.root,), name="work SDK warmup", daemon=True).start()

    def observe_meeting(self, store: MeetingStore) -> None:
        """Canvas intake failures must not fail a recording or its transcription."""
        try:
            self.personal.observe_meeting(store)
        except Exception as error:
            log(f"Meeting canvas intake failed: {error}. The journal is saved; startup will retry intake.")

    def create_personal(self, tasks: TaskStore) -> PersonalWork:
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

    def run(self) -> None:
        self.capture_timer = control_policy.initialize_controls(self.window.handle, self.startup.start, self.startup_effects)
        self.timings.mark("workers and readiness")
        self.desktop.send(WorkChanged(replace(self.agent.snapshot(), personal=self.personal.snapshot())))
        if self.settings.api_key:
            threading.Thread(target=self.agent.prepare, name="agent session warmup", daemon=True).start()
        system.run_message_loop()

    def quit(self) -> None:
        timings = Timings("shutdown")
        if self.capture_timer is not None:
            system.kill_window_timer(self.window.handle, self.capture_timer)
            self.capture_timer = None
        self.assistant.stop_capture(discard=True, reason="shutdown")
        timings.mark("stop capture")
        # Park running work while the owners its calls reach still exist.
        self.automation.close()
        timings.mark("worker")
        self.agent.close()
        if not self.agent.wait_closed(timeout=12):
            raise RuntimeError("The work frontend did not drain before shutdown.")
        timings.mark("work frontend")
        self.personal.close()
        timings.mark("personal work")
        self.triage.close()
        timings.mark("feed triage")
        self.communications.close()
        timings.mark("Teams worker")
        self.automatic_meetings.close()
        try:
            self.meetings.close()
        except OSError as error:
            log(str(error))
        timings.mark("meetings")
        self.activity.close()
        self.view_thread.close()
        self.levels.close()
        self.jobs.put(None)
        self.machine.close_microphone()
        self.window.destroy()
        system.close_event(self.mic_event)
        timings.mark("microphone cleanup")
        system.post_quit()

    def show_agent(self) -> None:
        self.agent.show()

    def stop_agent(self) -> None:
        self.agent.stop()

    def toggle_meeting(self) -> None:
        self.recording_action("stop" if self.meetings.snapshot().capturing else "start")

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

    # ---- what the desktop shows --------------------------------------------------------

    def show(self, state: State) -> None:
        self.levels.listen(enabled=self.assistant.listening is not None)
        if self.assistant.listening is not None:
            state = State.LISTENING
        if state in (State.READY, State.LAYOUT_OFF) and self.agent.running():
            state = State.NEEDS_INPUT if self.agent.window is not None and self.agent.window.waiting else State.AGENT
        self.desktop.send(VoiceChanged(state, agent_speaking=self.assistant.listening is Tool.AGENT_VOICE))

    def job_changed(self, job: Job | None) -> None:
        self.desktop.send(JobChanged(job))

    def notify(self, title: str, text: str) -> None:
        self.desktop.send(Notify(title, text))

    def problem(self, message: str) -> None:
        log(message)
        self.desktop.send(Notify("Workspace", message, warning=True))

    def recording_changed(self, state: RecordingState) -> None:
        self.desktop.send(RecordingChanged(state))
        self.agent.prepare()
        if self.agent.window is not None:
            self.agent.window.recording(state)
        prior, self._recording_phase = self._recording_phase, state.phase
        failed_capture = prior in ("starting", "recording", "stopping") and state.phase == "finishing" and bool(state.detail)
        if (prior != state.phase and state.phase in ("paused", "interrupted")) or failed_capture:
            self.desktop.send(
                Notify(
                    "Meeting transcript",
                    state.detail or "Recording was interrupted. Choose Open meeting transcripts for the saved part.",
                    warning=True,
                )
            )
        self.show(State.LISTENING if self.assistant.listening is not None else State.READY if self.assistant.layout_on else State.LAYOUT_OFF)

    def recording_action(self, action: RecordingAction) -> None:
        try:
            match action:
                case "start":
                    self.automatic_meetings.start_recording("both")
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
        self.desktop.send(
            Notify(
                "Automatic Teams recording",
                "Meeting detection is unavailable. Check the browser connection or choose Record a meeting manually.",
                warning=True,
            )
        )

    def review_feed(self, batch: tuple[Candidate, ...], rules: tuple[str, ...]) -> str:
        research = Research(self.settings, self.triage.research_context, self.triage.research_conversation, stop=self.triage.closed)
        return classify(self.settings, batch, rules, working_context=self.triage.working_context(batch), research=research)

    def work_changed(self, snapshot: WorkSnapshot) -> None:
        self.canvas.observe_work(snapshot)
        self.triage.context_changed(snapshot.tasks, snapshot.context)
        self.desktop.send(WorkChanged(replace(snapshot, personal=self.personal.snapshot())))

    def personal_changed(self, view: PersonalView) -> None:
        self.canvas.observe_catalog(view.catalog)
        self.desktop.send(WorkChanged(replace(self.agent.snapshot(), personal=view)))

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
            case ReadMeeting(transcript_path=path, offset=offset):
                try:
                    page = MeetingStore(Path(path).parent).conversation(offset)
                except OSError, ValueError, sqlite3.Error:
                    page = None
                self.desktop.send(MeetingPage(path, page))
            case OpenWorkSource(source_id):
                source = next((source for source in self.personal.snapshot().catalog.sources if source.id == source_id), None)
                if source is None:
                    raise ValueError("This source is no longer available. Refresh My work.")
                if isinstance(source, MeetingSource):
                    self.open_meeting_file(Path(source.meeting.transcript_path))
                    return
                if source.kind in (SourceKind.DOCUMENT, SourceKind.WEB_PAGE):
                    self.desktop.send(OpenReference(source.url))
                    return
                self.agent.start(source_request(source))
            case _:
                self.agent.command(command)

    def show_work(self) -> None:
        self.desktop.send(ShowWork(focus=True))
        self.agent.refresh()

    def open_meeting_file(self, path: Path) -> None:
        self.jobs.put(control_policy.meeting_file_job(path, os.startfile, self.problem))

    def meeting_command(self, command: StartMeeting | MeetingCommand) -> str:
        """Execute the agent's meeting request with the existing capture owner."""
        try:
            match command:
                case StartMeeting(source, title):
                    self.automatic_meetings.start_recording(source, title)
                case MeetingCommand.STOP:
                    self.automatic_meetings.stop_recording()
                case MeetingCommand.RETRY:
                    self.meetings.retry()
                case MeetingCommand.LIST:
                    return self.meetings.recent()
                case MeetingCommand.STATUS:
                    pass
                case _:
                    assert_never(command)
            return self.meetings.describe()
        except ValueError as error:
            raise OSError(str(error)) from error

    def agent_done(self) -> None:
        if self.assistant.listening is None:
            self.assistant.idle()

    def run_agent(self, text: str) -> None:
        """Spoken words for the agent: the desktop routes them by its focus; without one, the conversation takes them."""
        if self.desktop.connected:
            self.desktop.send(RouteSpeech(text))
        else:
            self.agent.voice(text)

    # ---- the desktop's commands (`DesktopCommands.Controls`) ---------------------------

    def use_tool(self, tool: Tool) -> None:
        self.assistant.handle(tool, down=True)

    def voice(self, text: str) -> None:
        self.agent.voice(text)

    def notify_canvas(self, title: str, target: str) -> None:
        self.agent.notify_canvas(title, target)

    def notices(self, observed: Observed) -> None:
        self.feed.notices(observed)

    def refresh(self) -> None:
        self.agent.refresh()

    def resume(self, task_id: str) -> None:
        self.agent.command(ControlTask(task_id, Control.RESUME))

    def received(self, frame: bytes) -> None:
        """Link thread: hand the desktop's command to the control thread, in order."""
        self.commands.put(frame)
        system.post_message(self.window.handle, WM_LINK, 0, 0)

    def drain_commands(self) -> None:
        while True:
            try:
                frame = self.commands.get_nowait()
            except queue.Empty:
                return
            try:
                self.commands_handler.handle(from_desktop(frame))
            except contracts.desktop_link.WireError as error:
                log(f"Refused a frame from the desktop: {error}")
            except (OSError, ValueError, sqlite3.Error) as error:
                self.problem(str(error))

    # ---- messages ----------------------------------------------------------------------

    def layout_changed(self, value: int) -> None:
        with contextlib.suppress(ValueError):
            self.layout = LayoutState(value)
        self.assistant.layout_on = self.layout is LayoutState.ON
        if not self.assistant.layout_on:
            self.assistant.stop_capture(reason="layout_off")
        if self.assistant.listening is None:
            self.assistant.idle()

    def on_message(self, hwnd: int, message: int, wparam: int, lparam: int) -> int | None:
        try:
            if message == system.WM_TIMER and wparam == self.capture_timer:
                self.assistant.expire_capture(time.monotonic())
                return 0
            if message == WM_LINK:
                self.drain_commands()
                return 0
            if message == WM_REQUEST:
                if (request := decode(wparam, APPS)) is not None:
                    self.assistant.handle(request, down=bool(lparam))
                return 0
            if message == WM_LAYOUT_STATE:
                self.layout_changed(wparam)
                return 0
            if message == system.WM_CLOSE:  # the keeper asks: it's restarting or installing
                self.quit()
                return 0
        except Exception:
            log(traceback.format_exc())
        return None


class Controller(Protocol):
    def run(self) -> None: ...


def run(
    settings: Settings | Missing,
    *,
    timings: Timings | None = None,
    window: components.Window = components.ASSISTANT.window,
    lock_name: str = LOCK_NAME,
) -> Exit:
    """Blocks until the keeper asks it to close; a test names its own `window` and `lock_name`."""
    screen.use_physical_pixels()  # before any window exists
    lock = system.create_lock(lock_name)
    if lock is None:
        return Exit.ALREADY_RUNNING
    try:
        timings = timings or Timings("startup")
        app: AssistantApp | None = None

        def received(frame: bytes) -> None:
            if app is not None:
                app.received(frame)

        published = components.endpoint("assistant")
        server = Server(os.urandom(24).hex(), received)
        app = AssistantApp(settings, LinkedDesktop(server), window=window)
        server.start(published)
        timings.mark("link")
        try:
            app.run()
        finally:
            server.close()
        return Exit.QUIT
    finally:
        system.release_lock(lock)


def show_error(message: str) -> None:
    system.message_box(message, "Workspace", system.MB_ICONHAND)
