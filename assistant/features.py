"""What each tool and app key does. Everything that touches Windows goes through a
`Desktop`, so the behaviour can be tested without Windows (like the layout's
engine and its `Host`).

Requests arrive on the thread that receives the layout's messages, and anything
quick happens right there: the microphone starts the moment a talk key goes down,
even while an earlier dictation is still being transcribed. Anything slow is
handed to the worker thread (`submit`), which does one job at a time, in order.
"""

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Literal, Protocol, assert_never

from assistant import prompts
from assistant.hotkeys import Route, needs_settings, route
from assistant.llm import MAX_SECONDS, Failure, Missing, Settings, ask, long_enough, transcribe, wav
from assistant.text import one_line_command, typed_text
from desktop_ui.icons import State
from desktop_ui.island_model import Job
from desktop_ui.navigation import AppKey, Order, Source, keyed
from diagnostics import failure_info
from protocol import App, Request, Tool
from usage import Detail
from winapi.pcm import RATE


class Desktop(Protocol):
    """What the assistant needs from Windows and its windows."""

    def start_listening(self) -> str | None:
        """Starts recording; a problem's description, or None."""

    def stop_listening(self) -> bytes:
        """Stops recording; 16-bit mono PCM at `RATE`."""
        ...

    def type_text(self, text: str) -> None: ...
    def set_clipboard(self, text: str) -> None: ...
    def show_state(self, state: State) -> None: ...
    def busy(self, job: Job | None) -> None:
        """The quick job now running, for the bar; None once it has finished."""

    def notify(self, title: str, text: str) -> None: ...
    def problem(self, message: str) -> None:
        """Something went wrong that the user should hear about."""

    def navigate(self, order: Order) -> None:
        """Hand a navigation or placement order to the desktop's window owner."""

    def arrange(self, tool: Tool, *, target: int | None) -> None:
        """Arrange the captured window, or the foreground window when target is None."""


Recorder = Callable[[str, Mapping[str, Detail]], None]
"""Writes one use of a feature to the usage log."""


class Controls(Protocol):
    """Assistant-owned effects; agent callbacks marshal their own worker invocations."""

    def run_agent(self, text: str) -> None: ...
    def show_agent(self) -> None: ...
    def stop_agent(self) -> None: ...
    def open_inbox(self) -> None: ...
    def switch_windows(self) -> None: ...
    def toggle_meeting(self) -> None: ...


def submit_voice_text(text: str, send: Callable[[str], None], details: dict[str, Detail]) -> None:
    """Measure submission, without retaining content or claiming the app displayed it."""
    details["requested_characters"] = len(text)
    details["phase"] = "submitting"
    started = time.monotonic()
    try:
        send(text)
        details["submitted_characters"] = len(text)
    finally:
        details["submit_seconds"] = round(time.monotonic() - started, 3)


@dataclass(frozen=True, slots=True)
class Capture:
    """The initiating request owns its release, even when tools share dictation."""

    identity: int
    source: Tool
    tool: Tool
    started: float


def listening_tool(source: Tool) -> Tool:
    match source:
        case Tool.DICTATE_TOGGLE:
            return Tool.DICTATE
        case Tool.AGENT_VOICE_TOGGLE:
            return Tool.AGENT_VOICE
        case _:
            return source


class Assistant:
    """Turns requests from the layout's tool and app keys into actions."""

    __slots__ = (
        "capture",
        "capture_id",
        "controls",
        "desktop",
        "latest_transcription",
        "layout_on",
        "missing",
        "record",
        "settings",
        "submit",
    )

    # Desktop, settings, scheduling, usage and controls form the key-feature composition seam.
    def __init__(  # noqa: PLR0913 - injected collaborators and callbacks
        self,
        desktop: Desktop,
        settings: Settings,
        *,
        record: Recorder,
        submit: Callable[[Callable[[], None]], None],
        controls: Controls,
        missing: Missing | None = None,
    ) -> None:
        self.desktop = desktop
        self.settings = settings
        self.record = record
        self.submit = submit
        """Runs a job on the worker thread, after whatever is already queued."""
        self.controls: Controls = controls
        self.capture: Capture | None = None
        self.capture_id = 0
        self.latest_transcription: str | None = None
        self.layout_on = True
        self.missing = missing
        """Settings the AI tools need but don't have; the other keys work without them."""

    # ---- requests ----------------------------------------------------------------------

    @property
    def listening(self) -> Tool | None:
        return self.capture.tool if self.capture is not None else None

    def handle(self, request: Request, *, down: bool, target: int | None = None) -> None:
        """Dispatch a key edge or menu press; only window arrangement uses target."""
        match request:
            case App():
                if down:
                    self.timed(f"app:{request.name}", lambda: self.order(AppKey(request, Source.KEY)))
                return
            case Tool():
                kind = route(request)
            case _:
                assert_never(request)
        if self.missing is not None and needs_settings(kind):
            if down:
                self.desktop.problem(f"Set {', '.join(self.missing.names)} to use the AI tools (see the README).")
            return
        if kind is not Route.HOLD and not down:
            return
        match kind:
            case Route.HOLD:
                self.hold(request, down=down)
            case Route.TOGGLE:
                if self.listening is not None:
                    self.stop_capture(reason="toggle")
                else:
                    self.hold(request, down=True)
            case Route.STOP:
                if self.listening is not None:
                    self.stop_capture(reason="stop")
                else:
                    self.controls.stop_agent()
            case Route.TRANSCRIPT:
                self.submit(self.copy_transcript)
            case Route.ARRANGE:
                self.submit(lambda: self.timed(request.name.lower(), lambda: self.arrange(request, target=target)))
            case Route.NAVIGATE:
                self.timed(request.name.lower(), lambda: self.order(keyed(request)))
            case Route.AGENT_SESSION:
                self.submit(lambda: self.timed(request.name.lower(), self.agent_session))
            case Route.INBOX:
                self.controls.open_inbox()
            case Route.SWITCHER:
                self.controls.switch_windows()
            case Route.MEETING:
                self.controls.toggle_meeting()
            case _:
                assert_never(kind)

    def idle(self) -> None:
        self.desktop.busy(None)
        self.desktop.show_state(State.READY if self.layout_on else State.LAYOUT_OFF)

    def working(self, job: Job) -> None:
        self.desktop.busy(job)
        self.desktop.show_state(State.WORKING)

    def timed(self, feature: str, job: Callable[[], Failure | None], *, extra: Mapping[str, Detail] | None = None) -> None:
        """Runs a job, reports a failure, and logs the use (never the content)."""
        started = time.monotonic()
        outcome: Failure | None = Failure("crashed")
        evidence: dict[str, Detail] = {}
        try:
            outcome = job()
        except Exception as error:
            evidence = failure_info(error).details()
            phase = (extra or {}).get("phase", "working")
            message = f"{feature.replace('_', ' ').title()} failed while {phase}. Please try again; diagnostic details are in Workspace's usage log."
            if phase == "submitting" and self.latest_transcription is not None:
                message = (
                    "Text submission failed. Your transcript is saved in Workspace and was copied to the clipboard if available. "
                    "Use Copy latest transcript in Workspace controls; check for partial text before pasting."
                )
            outcome = Failure(message)
        finally:
            details: dict[str, Detail] = {
                **(extra or {}),
                **evidence,
                "ok": not isinstance(outcome, Failure),
                "seconds": round(time.monotonic() - started, 2),
            }
            if isinstance(outcome, Failure):
                details["error"] = outcome.message[:120]
                self.desktop.problem(outcome.message)
            self.record(feature, details)
            if self.listening is None:
                self.idle()

    def hold(self, tool: Tool, *, down: bool) -> None:
        if down:
            if self.capture is not None:
                return
            self.capture_id += 1
            capture = Capture(self.capture_id, tool, listening_tool(tool), time.monotonic())
            try:
                problem = self.desktop.start_listening()
            except Exception as error:
                self.capture_problem(capture, "starting", error)
                # A start may have acquired the device before failing.
                try:
                    self.desktop.stop_listening()
                except Exception as cleanup:
                    self.capture_problem(capture, "cleanup", cleanup)
                self.idle()
                return
            if problem is not None:
                self.desktop.problem(problem)
                self.record(capture.tool.name.lower(), {"capture_id": capture.identity, "phase": "starting", "ok": False, "error": problem[:120]})
                self.idle()
                return
            self.capture = capture
            self.record("voice_capture", {"capture_id": capture.identity, "phase": "recording", "source": capture.source.name.lower()})
            self.desktop.show_state(State.LISTENING)
        elif self.capture is not None and tool is self.capture.source:
            self.stop_capture()

    def capture_problem(self, capture: Capture, phase: str, error: Exception) -> None:
        self.record(
            capture.tool.name.lower(),
            {
                "capture_id": capture.identity,
                "phase": phase,
                "ok": False,
                **failure_info(error).details(),
            },
        )
        message = str(error) if isinstance(error, OSError) else f"Voice capture failed while {phase}. Please try again; see Workspace's usage log."
        self.desktop.problem(message)

    def stop_capture(
        self,
        *,
        discard: bool = False,
        reason: Literal["released", "stop", "toggle", "layout_off", "shutdown", "limit"] = "released",
        now: float | None = None,
    ) -> bool:
        capture, self.capture = self.capture, None
        if capture is None:
            return False
        held_seconds = (time.monotonic() if now is None else now) - capture.started
        try:
            pcm = self.desktop.stop_listening()
        except Exception as error:
            self.capture_problem(capture, "stopping", error)
            self.idle()
            return False
        lengths: dict[str, Detail] = {
            "capture_id": capture.identity,
            "source": capture.source.name.lower(),
            "stop_reason": reason,
            "held_seconds": round(held_seconds, 2),
            "audio_seconds": round(len(pcm) / (RATE * 2), 2),
        }
        if discard or not long_enough(pcm):
            self.record("voice_capture", {**lengths, "phase": "cancelled" if discard else "too_short"})
            self.idle()
            return False
        self.working(Job.TRANSCRIBING)
        tool = capture.tool
        self.record("voice_capture", {**lengths, "phase": "queued"})
        try:
            self.submit(lambda: self.timed(tool.name.lower(), lambda: self.heard(tool, pcm, lengths), extra=lengths))
        except Exception as error:
            self.capture_problem(capture, "queueing", error)
            self.idle()
            return False
        return True

    def expire_capture(self, now: float) -> None:
        """Recover a lost release/toggle at the microphone's existing buffer limit."""
        if self.capture is not None and now >= self.capture.started + MAX_SECONDS and self.stop_capture(reason="limit", now=now):
            self.desktop.notify("Recording finished", "The five-minute voice limit was reached; your recording was queued for transcription.")

    # ---- the tools ---------------------------------------------------------------------

    def heard(self, tool: Tool, pcm: bytes, details: dict[str, Detail]) -> Failure | None:
        details["phase"] = "transcribing"
        started = time.monotonic()
        try:
            transcript = transcribe(self.settings, wav(pcm, RATE))
        finally:
            details["transcribe_seconds"] = round(time.monotonic() - started, 3)
        if isinstance(transcript, Failure):
            return transcript
        details["transcript_characters"] = len(transcript)
        self.remember_transcript(transcript)
        match tool:
            case Tool.DICTATE:
                submit_voice_text(typed_text(transcript), self.desktop.type_text, details)
            case Tool.DICTATE_CLEAN:
                details["phase"] = "cleaning"
                if isinstance(cleaned := ask(self.settings, prompts.CLEAN_DICTATION, transcript), Failure):
                    return cleaned
                self.remember_transcript(cleaned)
                submit_voice_text(typed_text(cleaned), self.desktop.type_text, details)
            case Tool.DICTATE_COMMAND:
                details["phase"] = "formatting"
                if isinstance(command := ask(self.settings, prompts.COMMAND, transcript), Failure):
                    return command
                self.remember_transcript(one_line_command(command))
                submit_voice_text(one_line_command(command), self.desktop.type_text, details)
            case Tool.AGENT_VOICE:
                submit_voice_text(transcript, self.controls.run_agent, details)
            case _:
                raise AssertionError(f"{tool} doesn't listen")
        return None

    def remember_transcript(self, text: str) -> None:
        """Keep recovery independent of both the clipboard and the insertion attempt."""
        if not text.strip():
            return
        self.latest_transcription = text
        try:
            self.desktop.set_clipboard(text)
        except OSError:
            self.desktop.problem("The clipboard is busy. Your transcript is saved; use Copy latest transcript in Workspace controls.")

    def copy_transcript(self) -> None:
        if self.latest_transcription is None:
            self.desktop.notify("No transcript yet", "Dictate first, then copy the latest transcript here.")
            return
        try:
            self.desktop.set_clipboard(self.latest_transcription)
        except OSError as error:
            self.desktop.problem(str(error))

    def arrange(self, tool: Tool, *, target: int | None) -> Failure | None:
        try:
            self.desktop.arrange(tool, target=target)
        except OSError as error:
            return Failure(str(error))
        return None

    def agent_session(self) -> None:
        self.controls.show_agent()

    def order(self, order: Order | None) -> None:
        if order is not None:
            self.desktop.navigate(order)
