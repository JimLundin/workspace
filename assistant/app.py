"""The assistant: dictation, meeting recording and the microphone, beside the desktop.

It runs without the desktop and the desktop without it. It never touches the
desktop's windows: it sends `contracts.desktop_link` messages through a
`DesktopPort` and takes the desktop's commands from the link. The keyboard
sends it only the requests it owns (dictation and meetings), to its own hidden
window.
"""

import contextlib
import os
import queue
import threading
import time
import traceback
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Final, assert_never

import components
import diagnostics
import usage
from assistant.control import (
    ControlState,
    Effect,
    Event,
    ExpireCapture,
    HandleFrame,
    HandleKey,
    JobReported,
    LayoutReported,
    Log,
    Notified,
    Problem,
    Quit,
    Record,
    RecordingUpdated,
    Send,
    Show,
    ShowIdle,
    Started,
    ToggleMeeting,
    UseLayout,
    idle_state,
    transition,
)
from config import APPS
from usage import DIRECTORY, Detail
lazy from assistant import control_policy
lazy from assistant.desktop import WinDesktop
lazy from assistant.desktop_port import DesktopPort, LevelFeed, LinkedDesktop
lazy from assistant.features import Assistant
lazy from assistant.lifecycle import Timings
lazy from assistant.llm import MAX_SECONDS, Missing, Settings
lazy from assistant.meeting_store import MeetingArchive
lazy from assistant.meetings import Meetings
lazy from contracts import desktop_link
lazy from contracts.desktop_link import UseTool, VoiceChanged, WireError, from_desktop
lazy from contracts.recording_state import RecordingAction
lazy from contracts.status import State
lazy from link.server import Server
lazy from protocol import WM_LAYOUT_STATE, WM_REQUEST, decode
lazy from winapi import audio, recording, screen, shell, system, windows
lazy from winapi.pcm import RATE

LOCK_NAME: Final = "Local\\workspace-assistant"
LOG: Final = DIRECTORY / "assistant.log"
WM_EVENTS: Final = system.WM_APP + 21
"""Any thread -> control thread: events are waiting in the inbox."""


def log(text: str) -> None:
    diagnostics.append(LOG, text)


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
    """Native timer and layout replay for the control-thread lifetime."""

    def find_window(self, title: str) -> int | None:
        return windows.find(title)

    # Match HWND, message and both payload fields of the native wire contract.
    def post(self, handle: int, message: int, wparam: int, lparam: int) -> bool:
        return system.post_message(handle, message, wparam, lparam)

    def start_timer(self, handle: int) -> int:
        return system.set_window_timer(handle, 1000)


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

    def toggle_meeting(self) -> None:
        self.report(ToggleMeeting())


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


@dataclass(frozen=True, slots=True)
class AssistantApp:
    """The assistant's parts, and the control thread that folds their events into effects.

    No part calls back into the application: each reports what happened to the
    inbox, and the control thread runs every event through `control.transition`
    and performs the effects it returns.
    """

    inbox: Inbox
    desktop: DesktopPort
    startup_effects: control_policy.StartupEffects
    timings: Timings
    mic_event: system.EventHandle
    machine: WinDesktop
    levels: LevelFeed
    meetings: Meetings
    assistant: Assistant
    jobs: queue.Queue[Callable[[], None] | None]
    worker: threading.Thread

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
        meetings = Meetings.open(
            usable,
            lambda source: recording.MeetingAudio(computer_audio=source == "both"),
            archive=MeetingArchive(DIRECTORY / "meetings"),
            on_update=lambda recorded: report(RecordingUpdated(recorded)),
            log=log,
        )
        timings.mark("meeting service")
        jobs: queue.Queue[Callable[[], None] | None] = queue.Queue()
        assistant = Assistant(machine, usable, record=_record, submit=jobs.put, controls=KeyControls(report), missing=missing)
        worker = threading.Thread(target=_run_jobs, args=(jobs, report), name="worker", daemon=True)
        if missing is not None:
            report(Notified("Workspace", f"Dictation and meeting transcripts need {', '.join(missing.names)}; the layout works without them."))
        return cls(
            inbox,
            desktop,
            NativeStartup() if startup_effects is None else startup_effects,
            timings,
            mic_event,
            machine,
            levels,
            meetings,
            assistant,
            jobs,
            worker,
        )

    # ---- the control loop --------------------------------------------------------------

    def start_workers(self) -> None:
        self.worker.start()
        self.meetings.start_worker()

    def run(self) -> None:
        handle = self.inbox.window.handle
        timer = control_policy.initialize_controls(handle, self.start_workers, self.startup_effects)
        self.timings.mark("workers")
        # The control loop owns the state: each event folds it, and nothing else holds it.
        state = self.handle(ControlState(), Started(timer))
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
            case Send(message):
                self.desktop.send(message)
            case Log(text):
                log(text)
            case Show(shown):
                listening = self.assistant.listening
                self.levels.listen(enabled=listening is not None)
                self.desktop.send(VoiceChanged(State.LISTENING if listening is not None else shown))
            case ShowIdle():
                self.perform(Show(idle_state(listening=self.assistant.listening, layout_on=self.assistant.layout_on)), state)
            case Record(action):
                self._record_meeting(action)
            case ToggleMeeting():
                self._record_meeting("stop" if self.meetings.snapshot().capturing else "start")
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
            case HandleFrame(frame):
                self._command(frame)
            case Quit():
                self.quit(state.capture_timer)
            case _:
                assert_never(effect)

    def _record_meeting(self, action: RecordingAction) -> None:
        try:
            match action:
                case "start":
                    self.meetings.start("both")
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
            self.inbox.report(Problem(str(error)))

    def _command(self, frame: bytes) -> None:
        try:
            match from_desktop(frame):
                case UseTool(tool=tool):
                    self.inbox.report(HandleKey(tool, down=True))
                case desktop_link.Record(action=action):
                    self._record_meeting(action)
        except WireError as error:
            log(f"Refused a frame from the desktop: {error}")

    def quit(self, capture_timer: int | None) -> None:
        timings = Timings("shutdown")
        if capture_timer is not None:
            system.kill_window_timer(self.inbox.window.handle, capture_timer)
        self.assistant.stop_capture(discard=True, reason="shutdown")
        timings.mark("stop capture")
        try:
            self.meetings.close()
        except OSError as error:
            log(str(error))
        timings.mark("meetings")
        self.levels.close()
        self.jobs.put(None)
        self.machine.close_microphone()
        self.inbox.window.destroy()
        system.close_event(self.mic_event)
        timings.mark("microphone cleanup")
        system.post_quit()


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
