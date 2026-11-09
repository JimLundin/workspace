"""Dictation, meeting recording and the microphone, which the desktop calls on its Qt thread.

What their worker threads report (the voice, a job, a notice, a problem, the
recording) reaches the desktop as events through its inbox. Slow dictation jobs
run one at a time on the worker thread.
"""

import os
import queue
import threading
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import diagnostics
from assistant.desktop import WinDesktop
from assistant.features import Assistant
from assistant.llm import MAX_SECONDS, Missing, Settings
from assistant.meeting_store import MeetingArchive
from assistant.meetings import Meetings
from components import DIRECTORY
from contracts.recording_state import RecordingAction
from contracts.status import State
from desktop_ui.desktop_control import Event, JobChanged, Notified, Problem, RecordingChanged, ShowVoice, idle_state
from winapi import audio, recording, system
from winapi.pcm import RATE


def configured(settings: Settings | Missing) -> tuple[Settings, Missing | None]:
    """The settings dictation and meetings run with and, when credentials are absent, what is missing."""
    match settings:
        case Missing():
            return Settings("", "", "", ""), settings
        case Settings():
            return settings, None


def _run_jobs(jobs: queue.Queue[Callable[[], None] | None], report: Callable[[Event], None], log: Callable[[str], None]) -> None:
    """The worker thread: slow jobs, one at a time."""
    while job := jobs.get():
        try:
            job()
        except Exception:
            log(traceback.format_exc())
            report(Problem("Something went wrong; it's in the desktop's log."))


@dataclass(frozen=True, slots=True)
class Voice:
    """The dictation keys, the meeting recorder and the microphone they share."""

    mic_event: system.EventHandle
    machine: WinDesktop
    meetings: Meetings
    dictation: Assistant
    jobs: queue.Queue[Callable[[], None] | None]
    worker: threading.Thread

    @classmethod
    def open(cls, settings: Settings | Missing, owner: int, report: Callable[[Event], None], log: Callable[[str], None]) -> Voice:
        """The owners over the default microphone; `owner` is the desktop's control window, which owns the clipboard."""
        mic_event = system.create_event()
        mic = audio.Microphone.open(RATE, MAX_SECONDS, mic_event)
        machine = WinDesktop.following(
            owner,
            mic,
            on_state=lambda shown: report(ShowVoice(shown)),
            on_job=lambda job: report(JobChanged(job)),
            on_notify=lambda title, text: report(Notified(title, text)),
            on_problem=lambda message: report(Problem(message)),
        )
        usable, missing = configured(settings)
        meetings = Meetings.open(
            usable,
            lambda source: recording.MeetingAudio(computer_audio=source == "both"),
            archive=MeetingArchive(DIRECTORY / "meetings"),
            on_update=lambda recorded: report(RecordingChanged(recorded)),
            log=log,
        )
        jobs: queue.Queue[Callable[[], None] | None] = queue.Queue()
        dictation = Assistant(
            machine, usable, failed=lambda feature, details: log(diagnostics.evidence(f"{feature} failed", details)), submit=jobs.put, missing=missing
        )
        worker = threading.Thread(target=_run_jobs, args=(jobs, report, log), name="worker", daemon=True)
        if missing is not None:
            report(Notified("Workspace", f"Dictation and meeting transcripts need {', '.join(missing.names)}; the layout works without them."))
        return cls(mic_event, machine, meetings, dictation, jobs, worker)

    def start(self) -> None:
        self.worker.start()
        self.meetings.start_worker()

    def level(self) -> float | None:
        """The microphone's level for the bar's trace, read off the Qt thread."""
        return self.machine.mic.level()

    def shown(self, state: State) -> State:
        """What the tray and the bar show for `state`: listening takes precedence."""
        return State.LISTENING if self.dictation.listening is not None else state

    def idle(self) -> State:
        return idle_state(listening=self.dictation.listening, layout_on=self.dictation.layout_on)

    def use_layout(self, *, on: bool) -> None:
        self.dictation.use_layout(on=on)
        if not on:
            self.dictation.stop_capture(reason="layout_off")
        if self.dictation.listening is None:
            self.dictation.idle()

    def toggle_meeting(self) -> None:
        self.record("stop" if self.meetings.snapshot().capturing else "start")

    def record(self, action: RecordingAction) -> None:
        """Raises OSError or ValueError when the recorder refuses `action`."""
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

    def close(self, log: Callable[[str], None]) -> None:
        """Finish a meeting's capture, drop a voice capture, and release the microphone."""
        self.dictation.stop_capture(discard=True, reason="shutdown")
        try:
            self.meetings.close()
        except OSError as error:
            log(str(error))
        self.jobs.put(None)
        self.machine.close_microphone()
        system.close_event(self.mic_event)
