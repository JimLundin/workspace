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
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Final, Protocol, assert_never

import components
import usage
from assistant.activity import ActivityTracker
from assistant.control import (
    AgentActivity,
    AgentDone,
    AgentStarted,
    AttendAutomatic,
    AutomaticShown,
    AutomaticUnavailable,
    CancelResearch,
    CanvasPublished,
    Command,
    ContinueRun,
    ControlState,
    Effect,
    Event,
    ExpireCapture,
    HandleFrame,
    HandleKey,
    IdleKeys,
    JobReported,
    LayoutReported,
    Log,
    Notices,
    Notified,
    NotifyCanvas,
    ObserveCatalog,
    ObserveWork,
    PersonalObserved,
    PrepareSession,
    Problem,
    Quit,
    Record,
    RecordingUpdated,
    RefreshWork,
    Resume,
    Send,
    SessionOpened,
    Show,
    ShowAgent,
    ShowAttention,
    ShowIdle,
    Speak,
    Started,
    StopAgent,
    TakeMeeting,
    ToggleMeeting,
    UseLayout,
    Voice,
    WorkObserved,
    WorkShown,
    idle_state,
    transition,
    tray_state,
)
from automation.activity import Observation, Policy
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
    MeetingPage,
    OpenReference,
    RouteSpeech,
    VoiceChanged,
    from_desktop,
)
lazy from contracts.meeting_detection import PREFERENCE
lazy from contracts.personal_work import (
    AddDocument,
    AddWebPage,
    DismissWork,
    MeetingSource,
    OpenWorkSource,
    RefreshPersonalWork,
    RestoreWork,
    SaveWork,
    SourceKind,
    UnlinkWork,
)
lazy from contracts.recording_state import RecordingAction
lazy from contracts.status import State
lazy from contracts.task import Control, RequestKind
lazy from contracts.work_commands import ControlTask, ReadMeeting, WorkViewCommand
lazy from link.server import Server
lazy from protocol import WM_LAYOUT_STATE, WM_REQUEST, Tool, decode
lazy from winapi import audio, recording, screen, shell, system, windows
lazy from winapi.pcm import RATE
lazy from winapi.shapes import Window
lazy from winapi.system_notices import Observed

ROOT: Final = Path(__file__).resolve().parent.parent
LOCK_NAME: Final = "Local\\workspace-assistant"
LOG: Final = DIRECTORY / "assistant.log"
WM_EVENTS: Final = system.WM_APP + 21
"""Any thread -> control thread: events are waiting in the inbox."""


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


@dataclass(frozen=True, slots=True)
class Inbox:
    """The control thread's events: any thread reports one and wakes the control window.

    The control loop reads the window's posted messages itself, so its procedure
    only turns a sent close into a posted one.
    """

    window: shell.AppWindow
    pending: queue.SimpleQueue[Event] = field(default_factory=queue.SimpleQueue[Event])

    @classmethod
    def open(cls, title: str) -> Inbox:
        def procedure(hwnd: int, message: int, _wparam: int, _lparam: int) -> int | None:
            if message == system.WM_CLOSE:
                system.post_message(hwnd, system.WM_CLOSE, 0, 0)
                return 0
            return None

        return cls(shell.AppWindow.create(title, procedure))

    def report(self, event: Event) -> None:
        """Any thread: queue `event` for the control thread."""
        self.pending.put(event)
        system.post_message(self.window.handle, WM_EVENTS, 0, 0)

    def drained(self) -> Iterator[Event]:
        """The events queued so far, oldest first."""
        while True:
            try:
                yield self.pending.get_nowait()
            except queue.Empty:
                return


@dataclass(frozen=True, slots=True)
class KeyControls:
    """What the keys ask of the application, reported to the control thread."""

    report: Callable[[Event], None]

    def run_agent(self, text: str) -> None:
        self.report(Speak(text))

    def show_agent(self) -> None:
        self.report(ShowAgent())

    def stop_agent(self) -> None:
        self.report(StopAgent())

    def toggle_meeting(self) -> None:
        self.report(ToggleMeeting())


@dataclass(frozen=True, slots=True)
class DesktopControls:
    """What the desktop's commands ask of the application, reported to the control thread."""

    report: Callable[[Event], None]

    def use_tool(self, tool: Tool) -> None:
        self.report(HandleKey(tool, down=True))

    def recording_action(self, action: RecordingAction) -> None:
        self.report(Record(action))

    def work_command(self, command: WorkViewCommand) -> None:
        self.report(Command(command))

    def voice(self, text: str) -> None:
        self.report(Voice(text))

    def notify_canvas(self, title: str, target: str) -> None:
        self.report(NotifyCanvas(title, target))

    def notices(self, observed: Observed) -> None:
        self.report(Notices(observed))

    def refresh(self) -> None:
        self.report(RefreshWork())

    def resume(self, task_id: str) -> None:
        self.report(Resume(task_id))

    def notify(self, title: str, text: str) -> None:
        self.report(Notified(title, text))

    def problem(self, message: str) -> None:
        self.report(Problem(message))


def _record(feature: str, details: Mapping[str, Detail]) -> None:
    with contextlib.suppress(OSError):
        usage.record("assistant", feature, details)


def _run_jobs(jobs: queue.Queue[Callable[[], None] | None], report: Callable[[Event], None]) -> None:
    """The worker thread: slow jobs, one at a time."""
    while (job := jobs.get()) is not None:
        try:
            job()
        except Exception:
            log(traceback.format_exc())
            report(Problem("Something went wrong; it's in the assistant's log."))


def _session_window(
    view_thread: ViewThread, desktop: DesktopPort, canvas: WorkCanvas, report: Callable[[Event], None], runner: WorkAgent
) -> AgentWindow:
    """The agent session: its snapshots go to the desktop and the canvas, from one view thread."""
    window = AgentWindow.open(
        runner.stop,
        post=view_thread.post,
        create_view=lambda _: SessionView(desktop, canvas.observe_session),
        on_problem=lambda message: report(Problem(message)),
        on_reset=runner.new_conversation,
        on_submit=runner.start,
        on_waiting=lambda waiting: report(Show(State.NEEDS_INPUT if waiting else State.AGENT)),
        on_recording=lambda action: report(Record(action)),
        on_work=lambda: report(WorkShown()),
        log=log,
    )
    report(SessionOpened(window))
    return window


def _review_feed(settings: Settings, batch: tuple[Candidate, ...], rules: tuple[str, ...], triage: Triage) -> str:
    research = Research(settings, triage.research_context, triage.research_conversation, stop=triage.closed)
    return classify(settings, batch, rules, working_context=triage.working_context(batch), research=research)


def _continue_run(agent: WorkAgent, canvas: WorkCanvas, run: CanvasRun) -> None:
    agent.watch(tuple(binding.task_id for binding in canvas.read().runs), owner="canvas")
    agent.submit_identified(run.task_id, run_prompt(run, canvas.title(run.work_id)), RequestKind.GENERAL)


def _meeting_command(automatic: AutomaticMeetings, meetings: Meetings, command: StartMeeting | MeetingCommand) -> str:
    """Execute the agent's meeting request with the existing capture owner."""
    try:
        match command:
            case StartMeeting(source, title):
                automatic.start_recording(source, title)
            case MeetingCommand.STOP:
                automatic.stop_recording()
            case MeetingCommand.RETRY:
                meetings.retry()
            case MeetingCommand.LIST:
                return meetings.recent()
            case MeetingCommand.STATUS:
                pass
            case _:
                assert_never(command)
        return meetings.describe()
    except ValueError as error:
        raise OSError(str(error)) from error


type Presented = Send | Log | Show | ShowIdle | IdleKeys | ShowAttention
type WorkEffect = ObserveWork | ObserveCatalog | ContinueRun | CancelResearch | Command | RefreshWork | Resume
type AgentEffect = Voice | NotifyCanvas | Notices | ShowAgent | StopAgent | Speak
type MeetingEffect = Record | ToggleMeeting | PrepareSession | TakeMeeting | AttendAutomatic
type KeyEffect = HandleKey | UseLayout | ExpireCapture


@dataclass(frozen=True, slots=True)
class AssistantApp:
    """The assistant's parts, and the control thread that folds their events into effects.

    No part calls back into the application: each reports what happened to the
    inbox, and the control thread runs every event through `control.transition`
    and performs the effects it returns.
    """

    inbox: Inbox
    settings: Settings
    desktop: DesktopPort
    startup_effects: control_policy.StartupEffects
    timings: Timings
    view_thread: ViewThread
    automatic_attention: AutomaticAttention
    mic_event: system.EventHandle
    machine: WinDesktop
    levels: LevelFeed
    automation: Worker
    activity: ActivityTracker
    canvas: WorkCanvas
    agent: WorkAgent
    personal: PersonalWork
    triage: Triage
    feed: FeedInbox
    communications: Communications
    commands: DesktopCommands
    meetings: Meetings
    automatic_meetings: AutomaticMeetings
    assistant: Assistant
    jobs: queue.Queue[Callable[[], None] | None]
    startup: WorkerStartup

    @classmethod
    def compose(
        cls,
        settings: Settings | Missing,
        desktop: DesktopPort,
        inbox: Inbox,
        *,
        startup_effects: control_policy.StartupEffects | None = None,
    ) -> AssistantApp:
        report = inbox.report
        timings = Timings("startup")
        view_thread = ViewThread.start()
        automatic_attention = AutomaticAttention(lambda status: report(AutomaticShown(status)), lambda: report(AutomaticUnavailable()))
        mic_event = system.create_event()
        mic = audio.Microphone.open(RATE, MAX_SECONDS, mic_event)
        machine = WinDesktop.following(
            inbox.window.handle,
            mic,
            on_state=lambda shown: report(Show(shown)),
            on_job=lambda job: report(JobReported(job)),
            on_notify=lambda title, text: report(Notified(title, text)),
            on_problem=lambda message: report(Problem(message)),
        )
        levels = LevelFeed.start(mic.level, desktop)
        timings.mark("control window and microphone")
        usable, missing = configured(settings)
        tasks = TaskStore(WORK.journal)
        saved_context = ContextStore(tasks.path)
        automation = Worker.leasing(tasks, WORK.root)
        policy = Policy(enabled=os.environ.get("WORKSPACE_AGENT_CONTEXT", "recent").lower() != "off")
        activity = ActivityTracker.of(foreground_context, policy=policy)
        canvas = WorkCanvas(
            WORK.root / "canvas.sqlite3",
            lambda run: report(ContinueRun(run)),
            lambda publication: report(CanvasPublished(publication)),
            autonomous=bool(usable.api_key and usable.base_url),
        )
        agent = WorkAgent.open(
            tasks,
            saved_context,
            automation,
            lambda runner: _session_window(view_thread, desktop, canvas, report, runner),
            on_snapshot=lambda snapshot: report(WorkObserved(snapshot)),
            on_done=lambda: report(AgentDone()),
            report_error=log,
            on_start=lambda: report(AgentStarted()),
            context=activity.snapshot,
        )
        timings.mark("work frontend")
        agent.watch(tuple(run.task_id for run in canvas.read().runs), owner="canvas")
        personal = PersonalWork.open(
            PersonalStore(tasks.path),
            BrowserSources(Browser.at(BROWSER_PROFILE, source=Product.EDGE)),
            lambda view: report(PersonalObserved(view)),
            model=Correlator(usable) if usable.api_key and usable.base_url else None,
            dismissed=lambda work: report(CancelResearch(work)),
        )
        if usable.api_key and usable.base_url:
            # Recover only the crash window between binding and task commit.
            for run in canvas.read().runs:
                match run:
                    case CanvasRun(intent=CanvasInstruction()) | CanvasRun(evidence=str()) if tasks.get(run.task_id) is None:
                        _continue_run(agent, canvas, run)
                    case _:
                        pass
        triage = Triage.start(
            windows_store(DIRECTORY / "work-feed.bin", STORED_BOARD),
            lambda batch, rules, triage: _review_feed(usable, batch, rules, triage),
            submit=agent.submit_identified,
            work=FeedWork(tasks, saved_context, activity.snapshot),
            personal=personal,
        )
        feed = FeedInbox.load(windows_store(DIRECTORY / "notifications.bin", NOTIFICATION_STATE), triage.observe)
        communications = Communications(
            TeamsWeb.at(BROWSER_PROFILE), windows_store(DIRECTORY / "communications.bin", COMMUNICATIONS_STATE), feed.communications
        )
        work_owners = WorkOwners(triage.command, personal.handle, canvas.command)
        commands = DesktopCommands(canvas, desktop, DesktopControls(report))
        timings.mark("communications and desktop owners")
        meetings = Meetings.open(
            usable,
            lambda source: recording.MeetingAudio(computer_audio=source == "both"),
            archive=MeetingArchive(DIRECTORY / "meetings"),
            on_update=lambda recorded: report(RecordingUpdated(recorded)),
            on_meeting=lambda store: report(TakeMeeting(store)),
            log=log,
        )
        automatic_meetings = AutomaticMeetings.load(
            meetings,
            TeamsCalls(Browser.at(BROWSER_PROFILE, source=Product.EDGE)),
            windows_store(DIRECTORY / "automatic-meetings.bin", PREFERENCE),
            publish=lambda status: report(AttendAutomatic(status)),
        )
        timings.mark("meeting services")
        jobs: queue.Queue[Callable[[], None] | None] = queue.Queue()
        assistant = Assistant(machine, usable, record=_record, submit=jobs.put, controls=KeyControls(report), missing=missing)

        def start_work() -> None:
            """Recover saved work before readiness; execution then runs on the worker's threads."""
            calls = OwnerCalls(tasks, work_owners.handle, lambda command: _meeting_command(automatic_meetings, meetings, command))
            runner, close_background = native_runner(
                usable, automation, calls, hwnd=inbox.window.handle, contexts=saved_context, context=activity.snapshot
            )
            automation.start(runner, agent.deliver, close_background)
            if usable.api_key:
                threading.Thread(target=warm_sdk, args=(WORK.root,), name="work SDK warmup", daemon=True).start()

        worker = threading.Thread(target=_run_jobs, args=(jobs, report), name="worker", daemon=True)
        startup = WorkerStartup(
            (
                start_work,
                activity.start,
                worker.start,
                agent.start_worker,
                personal.start,
                communications.start,
                meetings.start_worker,
                automatic_meetings.start,
            )
        )
        if missing is not None:
            report(Notified("Workspace", f"The AI tools need {', '.join(missing.names)}; the layout works without them."))
        return cls(
            inbox,
            usable,
            desktop,
            NativeStartup() if startup_effects is None else startup_effects,
            timings,
            view_thread,
            automatic_attention,
            mic_event,
            machine,
            levels,
            automation,
            activity,
            canvas,
            agent,
            personal,
            triage,
            feed,
            communications,
            commands,
            meetings,
            automatic_meetings,
            assistant,
            jobs,
            startup,
        )

    # ---- the control loop --------------------------------------------------------------

    def run(self) -> None:
        handle = self.inbox.window.handle
        timer = control_policy.initialize_controls(handle, self.startup.start, self.startup_effects)
        self.timings.mark("workers and readiness")
        # The control loop owns the state: each event folds it, and nothing else holds it.
        state = self.handle(ControlState(), Started(timer, self.agent.snapshot(), self.personal.snapshot()))
        if self.settings.api_key:
            threading.Thread(target=self.agent.prepare, name="agent session warmup", daemon=True).start()
        for message in system.messages_for(handle):
            for event in self._events(message, state.capture_timer):
                state = self.handle(state, event)

    def _events(self, message: system.Message, capture_timer: int | None) -> Iterator[Event]:
        """What a message posted to the control window reports."""
        if message.message == WM_EVENTS:
            yield from self.inbox.drained()
        elif message.message == system.WM_TIMER and message.wparam == capture_timer:
            yield ExpireCapture(time.monotonic())
        elif message.message == WM_REQUEST:
            if (request := decode(message.wparam, APPS)) is not None:
                yield HandleKey(request, down=bool(message.lparam))
        elif message.message == WM_LAYOUT_STATE:
            yield LayoutReported(message.wparam)
        elif message.message == system.WM_CLOSE:
            yield Quit()

    def handle(self, state: ControlState, event: Event) -> ControlState:
        """Control thread: fold `event` into `state`, perform its effects in order, and return the new state."""
        state, effects = transition(state, event)
        for effect in effects:
            try:
                self.perform(effect, state)
            except Exception:
                log(traceback.format_exc())
        return state

    def perform(self, effect: Effect, state: ControlState) -> None:
        match effect:
            case Send() | Log() | Show() | ShowIdle() | IdleKeys() | ShowAttention():
                self._present(effect)
            case ObserveWork() | ObserveCatalog() | ContinueRun() | CancelResearch() | Command() | RefreshWork() | Resume():
                self._work(effect)
            case Voice() | NotifyCanvas() | Notices() | ShowAgent() | StopAgent() | Speak():
                self._converse(effect)
            case Record() | ToggleMeeting() | PrepareSession() | TakeMeeting() | AttendAutomatic():
                self._meet(effect)
            case HandleKey() | UseLayout() | ExpireCapture():
                self._key(effect)
            case HandleFrame(frame):
                self._command(frame, state.session)
            case Quit():
                self.quit(state.capture_timer)
            case AgentActivity(active):
                self.activity.agent_working(active=active)
            case _:
                assert_never(effect)

    # ---- performing effects ------------------------------------------------------------

    def _present(self, effect: Presented) -> None:
        match effect:
            case Send(message):
                self.desktop.send(message)
            case Log(text):
                log(text)
            case Show(shown):
                listening = self.assistant.listening
                self.levels.listen(enabled=listening is not None)
                waiting = self.agent.window is not None and self.agent.window.waiting
                shown = tray_state(shown, listening=listening, running=self.agent.running(), waiting=waiting)
                self.desktop.send(VoiceChanged(shown, agent_speaking=listening is Tool.AGENT_VOICE))
            case ShowIdle():
                self._present(Show(idle_state(listening=self.assistant.listening, layout_on=self.assistant.layout_on)))
            case IdleKeys():
                if self.assistant.listening is None:
                    self.assistant.idle()
            case ShowAttention(session, attention):
                session.canvas_attention(attention)
            case _:
                assert_never(effect)

    def _work(self, effect: WorkEffect) -> None:
        match effect:
            case ObserveWork(snapshot):
                self.canvas.observe_work(snapshot)
                self.triage.context_changed(snapshot.tasks, snapshot.context)
            case ObserveCatalog(catalog):
                self.canvas.observe_catalog(catalog)
            case ContinueRun(run):
                _continue_run(self.agent, self.canvas, run)
            case CancelResearch(work):
                # The committed user dismissal owns cancellation of only its research.
                for run in self.canvas.read().runs:
                    if run.work_id == work.id:
                        self.agent.command(ControlTask(run.task_id, Control.CANCEL))
            case Command(command):
                self._work_command(command)
            case RefreshWork():
                self.agent.refresh()
            case Resume(task_id):
                self.agent.command(ControlTask(task_id, Control.RESUME))
            case _:
                assert_never(effect)

    def _converse(self, effect: AgentEffect) -> None:
        match effect:
            case Voice(text):
                self.agent.voice(text)
            case NotifyCanvas(title, target):
                self.agent.notify_canvas(title, target)
            case Notices(observed):
                self.feed.notices(observed)
            case ShowAgent():
                self.agent.show()
            case StopAgent():
                self.agent.stop()
            case Speak(text):
                # The desktop routes spoken words by its focus; without one, the conversation takes them.
                if self.desktop.connected:
                    self.desktop.send(RouteSpeech(text))
                else:
                    self.agent.voice(text)
            case _:
                assert_never(effect)

    def _meet(self, effect: MeetingEffect) -> None:
        match effect:
            case Record(action):
                self._record_meeting(action)
            case ToggleMeeting():
                self._record_meeting("stop" if self.meetings.snapshot().capturing else "start")
            case PrepareSession(recorded):
                self.agent.prepare()
                if self.agent.window is not None:
                    self.agent.window.recording(recorded)
            case TakeMeeting(store):
                # Canvas intake failures must not fail a recording or its transcription.
                try:
                    self.personal.observe_meeting(store)
                except Exception as error:
                    log(f"Meeting canvas intake failed: {error}. The journal is saved; startup will retry intake.")
            case AttendAutomatic(status):
                self.automatic_attention.changed(status)
            case _:
                assert_never(effect)

    def _key(self, effect: KeyEffect) -> None:
        match effect:
            case HandleKey(request, down):
                self.assistant.handle(request, down=down)
            case UseLayout(on):
                self.assistant.use_layout(on=on)
                if not on:
                    self.assistant.stop_capture(reason="layout_off")
                if self.assistant.listening is None:
                    self.assistant.idle()
            case ExpireCapture(at):
                self.assistant.expire_capture(at)
            case _:
                assert_never(effect)

    def _record_meeting(self, action: RecordingAction) -> None:
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
            self.inbox.report(Problem(str(error)))

    def _work_command(self, command: WorkViewCommand) -> None:
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
                    report = self.inbox.report
                    self.jobs.put(
                        control_policy.meeting_file_job(Path(source.meeting.transcript_path), os.startfile, lambda message: report(Problem(message)))
                    )
                    return
                if source.kind in (SourceKind.DOCUMENT, SourceKind.WEB_PAGE):
                    self.desktop.send(OpenReference(source.url))
                    return
                self.agent.start(source_request(source))
            case _:
                self.agent.command(command)

    def _command(self, frame: bytes, session: AgentWindow | None) -> None:
        try:
            self.commands.handle(from_desktop(frame), session)
        except contracts.desktop_link.WireError as error:
            log(f"Refused a frame from the desktop: {error}")
        except (OSError, ValueError, sqlite3.Error) as error:
            self.inbox.report(Problem(str(error)))

    def quit(self, capture_timer: int | None) -> None:
        timings = Timings("shutdown")
        if capture_timer is not None:
            system.kill_window_timer(self.inbox.window.handle, capture_timer)
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
        self.inbox.window.destroy()
        system.close_event(self.mic_event)
        timings.mark("microphone cleanup")
        system.post_quit()


class Controller(Protocol):
    def run(self) -> None: ...


def run(
    settings: Settings | Missing,
    *,
    timings: Timings | None = None,
    window: components.Window = components.ASSISTANT.window,
    lock_name: str = LOCK_NAME,
) -> Exit:
    """Blocks until asked to close; a test names its own `window` and `lock_name`."""
    screen.use_physical_pixels()  # before any window exists
    lock = system.create_lock(lock_name)
    if lock is None:
        return Exit.ALREADY_RUNNING
    try:
        timings = timings or Timings("startup")
        inbox = Inbox.open(window.title)
        published = components.endpoint("assistant")
        server = Server.listen(os.urandom(24).hex(), lambda frame: inbox.report(HandleFrame(frame)))
        app = AssistantApp.compose(settings, LinkedDesktop(server), inbox)
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
