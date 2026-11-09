"""What each tool and app key does. Everything that touches Windows goes through a
`Desktop`, so the behaviour can be tested without Windows (like the layout's
engine and its `Host`).

Requests arrive on the desktop's Qt thread, which receives the layout's
messages, and anything quick happens right there: the microphone starts the moment a talk key goes down,
even while an earlier dictation is still being transcribed. Anything slow is
handed to the worker thread (`submit`), which does one job at a time, in order.
"""

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from typing import Final, Literal, Protocol, assert_never

from assistant.llm import MAX_SECONDS, Failure, Missing, Settings, long_enough, transcribe, wav
from assistant.text import typed_text
from cell import Cell
from contracts.hotkeys import NEEDS_SETTINGS, ROUTES, Route
from contracts.status import Job, State
from diagnostics import Detail, failure_info
from protocol import Tool
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


Recorder = Callable[[str, Mapping[str, Detail]], None]
"""Writes a feature's failure and its evidence (never content) to the desktop's log."""


@dataclass(frozen=True, slots=True)
class Progress:
    """A job's diagnostic details so far, kept for `Features.timed` even when the job raises.

    The job notes each phase as it reaches it; each note replaces the held
    `frozendict`, so a reader never sees one change partway through.
    """

    _details: Cell[frozendict[str, Detail]]

    @classmethod
    def of(cls, details: Mapping[str, Detail]) -> Progress:
        return cls(Cell(frozendict(details)))

    @property
    def details(self) -> frozendict[str, Detail]:
        return self._details.get()

    def note(self, **details: Detail) -> None:
        self._details.update(lambda noted: noted | details)


def submit_voice_text(text: str, send: Callable[[str], None], progress: Progress) -> None:
    """Measure submission, without retaining content or claiming the app displayed it."""
    progress.note(requested_characters=len(text), phase="submitting")
    started = time.monotonic()
    try:
        send(text)
        progress.note(submitted_characters=len(text))
    finally:
        progress.note(submit_seconds=round(time.monotonic() - started, 3))


@dataclass(frozen=True, slots=True)
class Capture:
    """The initiating request owns its release, even when tools share dictation."""

    identity: int
    source: Tool
    tool: Tool
    started: float


LISTENING_TOOLS: Final[frozendict[Tool, Tool]] = frozendict({Tool.DICTATE_TOGGLE: Tool.DICTATE})
"""A toggle listens as its hold tool; every other tool listens as itself."""


def listening_tool(source: Tool) -> Tool:
    return LISTENING_TOOLS.get(source, source)


@dataclass(frozen=True, slots=True)
class _Keys:
    capture: Capture | None = None
    """The voice capture in progress."""
    capture_id: int = 0
    """The last capture's identity."""
    latest_transcription: str | None = None
    layout_on: bool = True


@dataclass(frozen=True, slots=True)
class Assistant:
    """Turns the dictation and transcript keys into actions."""

    # Desktop, settings, scheduling and the failure log form the key-feature composition seam.
    desktop: Desktop
    settings: Settings
    failed: Recorder = field(kw_only=True)
    submit: Callable[[Callable[[], None]], None] = field(kw_only=True)
    """Runs a job on the worker thread, after whatever is already queued."""
    missing: Missing | None = field(default=None, kw_only=True)
    """Settings the AI tools need but don't have; the other keys work without them."""
    clock: Callable[[], float] = field(default=time.monotonic, kw_only=True)
    """When a voice capture starts and stops, for its time limit."""
    _state: Cell[_Keys] = field(default_factory=lambda: Cell(_Keys()), init=False, repr=False)

    @property
    def capture(self) -> Capture | None:
        return self._state.get().capture

    @property
    def latest_transcription(self) -> str | None:
        return self._state.get().latest_transcription

    @property
    def layout_on(self) -> bool:
        return self._state.get().layout_on

    def use_layout(self, *, on: bool) -> None:
        """Record whether the keyboard layout is on, which decides the idle state shown."""
        self._state.set(replace(self._state.get(), layout_on=on))

    # ---- requests ----------------------------------------------------------------------

    @property
    def listening(self) -> Tool | None:
        return capture.tool if (capture := self.capture) is not None else None

    def handle(self, tool: Tool, *, down: bool) -> None:
        """Dispatch a key edge or menu press."""
        kind = ROUTES[tool]
        if self.missing is not None and NEEDS_SETTINGS[kind]:
            if down:
                self.desktop.problem(f"Set {', '.join(self.missing.names)} to use the AI tools (see the README).")
            return
        if kind is not Route.HOLD and not down:
            return
        match kind:
            case Route.HOLD:
                self.hold(tool, down=down)
            case Route.TOGGLE:
                if self.listening is not None:
                    self.stop_capture(reason="toggle")
                else:
                    self.hold(tool, down=True)
            case Route.TRANSCRIPT:
                self.submit(self.copy_transcript)
            case Route.NAVIGATE | Route.SWITCHER | Route.MEETING:
                pass  # The desktop's own (see `desktop_ui.desktop_control`).
            case _:
                assert_never(kind)

    def idle(self) -> None:
        self.desktop.busy(None)
        self.desktop.show_state(State.READY if self._state.get().layout_on else State.LAYOUT_OFF)

    def working(self, job: Job) -> None:
        self.desktop.busy(job)
        self.desktop.show_state(State.WORKING)

    def timed(self, feature: str, job: Callable[[], Failure | None], *, progress: Progress | None = None) -> None:
        """Runs a job, and reports and logs a failure (never the content) with the details the job noted."""
        started = time.monotonic()
        outcome: Failure | None = Failure("crashed")
        evidence: dict[str, Detail] = {}
        try:
            outcome = job()
        except Exception as error:
            evidence = failure_info(error).details()
            phase = progress.details.get("phase", "working") if progress is not None else "working"
            message = (
                f"{feature.replace('_', ' ').title()} failed while {phase}. Please try again; diagnostic details are in Workspace's desktop log."
            )
            if phase == "submitting" and self._state.get().latest_transcription is not None:
                message = (
                    "Text submission failed. Your transcript is saved in Workspace and was copied to the clipboard if available. "
                    "Use Copy latest transcript in Workspace controls; check for partial text before pasting."
                )
            outcome = Failure(message)
        finally:
            details: dict[str, Detail] = {
                **(progress.details if progress is not None else {}),
                **evidence,
                "seconds": round(time.monotonic() - started, 2),
            }
            if isinstance(outcome, Failure):
                details["error"] = outcome.message[:120]
                self.desktop.problem(outcome.message)
                self.failed(feature, details)
            if self.listening is None:
                self.idle()

    def hold(self, tool: Tool, *, down: bool) -> None:
        if down:
            if self._state.get().capture is not None:
                return
            identity = self._state.get().capture_id + 1
            self._state.set(replace(self._state.get(), capture_id=identity))
            capture = Capture(identity, tool, listening_tool(tool), self.clock())
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
                self.failed(capture.tool.name.lower(), {"capture_id": capture.identity, "phase": "starting", "error": problem[:120]})
                self.idle()
                return
            self._state.set(replace(self._state.get(), capture=capture))
            self.desktop.show_state(State.LISTENING)
        elif (held := self.capture) is not None and tool is held.source:
            self.stop_capture()

    def capture_problem(self, capture: Capture, phase: str, error: Exception) -> None:
        self.failed(
            capture.tool.name.lower(),
            {
                "capture_id": capture.identity,
                "phase": phase,
                **failure_info(error).details(),
            },
        )
        message = str(error) if isinstance(error, OSError) else f"Voice capture failed while {phase}. Please try again; see Workspace's desktop log."
        self.desktop.problem(message)

    def stop_capture(
        self,
        *,
        discard: bool = False,
        reason: Literal["released", "stop", "toggle", "layout_off", "shutdown", "limit"] = "released",
        now: float | None = None,
    ) -> bool:
        capture = self._state.get().capture
        self._state.set(replace(self._state.get(), capture=None))
        if capture is None:
            return False
        held_seconds = (self.clock() if now is None else now) - capture.started
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
            self.idle()
            return False
        self.working(Job.TRANSCRIBING)
        tool = capture.tool
        try:
            progress = Progress.of(lengths)
            self.submit(lambda: self.timed(tool.name.lower(), lambda: self.heard(tool, pcm, progress), progress=progress))
        except Exception as error:
            self.capture_problem(capture, "queueing", error)
            self.idle()
            return False
        return True

    def expire_capture(self, now: float) -> None:
        """Recover a lost release/toggle at the microphone's existing buffer limit."""
        if (held := self.capture) is not None and now >= held.started + MAX_SECONDS and self.stop_capture(reason="limit", now=now):
            self.desktop.notify("Recording finished", "The five-minute voice limit was reached; your recording was queued for transcription.")

    # ---- the tools ---------------------------------------------------------------------

    def heard(self, tool: Tool, pcm: bytes, progress: Progress) -> Failure | None:
        progress.note(phase="transcribing")
        started = time.monotonic()
        try:
            transcript = transcribe(self.settings, wav(pcm, RATE))
        finally:
            progress.note(transcribe_seconds=round(time.monotonic() - started, 3))
        if isinstance(transcript, Failure):
            return transcript
        progress.note(transcript_characters=len(transcript))
        self.remember_transcript(transcript)
        match tool:
            case Tool.DICTATE:
                submit_voice_text(typed_text(transcript), self.desktop.type_text, progress)
            case _:
                raise AssertionError(f"{tool} doesn't listen")
        return None

    def remember_transcript(self, text: str) -> None:
        """Keep recovery independent of both the clipboard and the insertion attempt."""
        if not text.strip():
            return
        self._state.set(replace(self._state.get(), latest_transcription=text))
        try:
            self.desktop.set_clipboard(text)
        except OSError:
            self.desktop.problem("The clipboard is busy. Your transcript is saved; use Copy latest transcript in Workspace controls.")

    def copy_transcript(self) -> None:
        if (transcript := self.latest_transcription) is None:
            self.desktop.notify("No transcript yet", "Dictate first, then copy the latest transcript here.")
            return
        try:
            self.desktop.set_clipboard(transcript)
        except OSError as error:
            self.desktop.problem(str(error))
