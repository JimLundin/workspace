"""What each tool and app key does. Everything that touches Windows goes through a
`Desktop`, so the behaviour can be tested without Windows (like the layout's
engine and its `Host`).

Requests arrive on the thread that receives the layout's messages, and anything
quick happens right there: the microphone starts the moment a talk key goes down,
even while an earlier dictation is still being transcribed. Anything slow is
handed to the worker thread (`submit`), which does one job at a time, in order.
"""

import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum, auto
from typing import Final, Literal, Protocol

from assistant import prompts
from assistant.geometry import Shot
from assistant.icons import State
from assistant.llm import (
    MAX_SECONDS,
    Failure,
    Image,
    Message,
    Missing,
    Part,
    Settings,
    Text,
    ask,
    assistant_message,
    long_enough,
    stream,
    system_message,
    transcribe,
    user_message,
    wav,
)
from assistant.text import one_line_command, typed_text, unwrap
from assistant.tiling_commands import TILING_COMMANDS
from config import REWRITES
from diagnostics import failure_info
from protocol import App, Request, Tool
from usage import Detail
from winapi.pcm import RATE
from winapi.shapes import Rect, Window


class Answer(Protocol):
    """A window showing an answer as it's written, with a box for follow-up questions."""

    def write(self, text: str) -> None: ...
    def finish(self) -> None:
        """The answer is complete; follow-up questions can be asked."""

    def fail(self, message: str) -> None: ...


class Desktop(Protocol):
    """What the assistant needs from Windows and its windows."""

    def start_listening(self) -> str | None:
        """Starts recording; a problem's description, or None."""

    def stop_listening(self) -> bytes:
        """Stops recording; 16-bit mono PCM at `RATE`."""
        ...

    def copy_selection(self) -> str | None:
        """The selected text, if any. Leaves the clipboard as it was."""

    def paste(self, text: str) -> None:
        """Replaces the selection (or types at the cursor), then restores the clipboard."""

    def type_text(self, text: str) -> None: ...
    def set_clipboard(self, text: str) -> None: ...
    def choose_region(self) -> Rect | None:
        """Lets the user drag over part of the screen; None if they press Escape."""

    def capture(self, area: Rect, longest: int) -> tuple[bytes, Shot]:
        """A PNG of the area, no bigger than `longest` pixels on its longer side."""
        ...

    def prompt(self, title: str) -> str | None:
        """A text box; what was typed, or None if cancelled."""

    def answer(self, title: str, follow_up: Callable[[str], None]) -> Answer: ...
    def show_state(self, state: State) -> None: ...
    def notify(self, title: str, text: str) -> None: ...
    def problem(self, message: str) -> None:
        """Something went wrong that the user should hear about."""

    def windows(self) -> list[Window]:
        """Windows on the taskbar, front to back."""
        ...

    def foreground(self) -> int: ...
    def focus(self, handle: int) -> bool: ...
    def launch(self, command: str) -> None: ...
    def arrange(self, tool: Tool) -> None:
        """Snap, maximize, minimize or move the front window (a window tool)."""


Recorder = Callable[[str, Mapping[str, Detail]], None]
"""Writes one use of a feature to the usage log."""


class Outcome(Enum):
    DONE = auto()
    CANCELLED = auto()
    """The user backed out (Escape in a box, no area chosen)."""


HOLD_TOOLS: Final = frozenset({Tool.DICTATE, Tool.DICTATE_CLEAN, Tool.DICTATE_COMMAND, Tool.REWRITE_VOICE, Tool.AGENT_VOICE})
"""Hold the key and speak: these listen until it's released."""
WINDOW_TOOLS: Final = frozenset({Tool.SNAP_LEFT, Tool.SNAP_RIGHT, Tool.MAXIMIZE, Tool.MINIMIZE, Tool.NEXT_MONITOR, *TILING_COMMANDS})
LOCAL_TOOLS: Final = frozenset({*WINDOW_TOOLS, Tool.STOP, Tool.COPY_TRANSCRIPT})
SCREENSHOT_SIZE: Final = 2048
"""Longest side of screenshots sent to the model, in pixels."""


def pick_window(windows: Sequence[Window], app: App, foreground: int) -> int | None:
    """The app's window to bring forward: its front one; or, if one of its windows is
    already in front, its rearmost, so pressing again goes through all of them."""
    mine = [w.handle for w in windows if w.exe == app.exe.lower() and app.title.lower() in w.title.lower()]
    if not mine:
        return None
    return mine[-1] if foreground in mine else mine[0]


def switcher_windows(windows: Sequence[Window], visible: frozenset[int], managed: frozenset[int]) -> tuple[Window, ...]:
    """Include hidden managed workspaces without exposing the shell's cloaked hosts."""
    eligible = visible | managed
    return tuple(window for window in windows if window.handle in eligible)


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


def voice_tool(source: Tool) -> Tool:
    match source:
        case Tool.DICTATE_TOGGLE:
            return Tool.DICTATE
        case Tool.AGENT_VOICE_TOGGLE:
            return Tool.AGENT_VOICE
        case _:
            return source


class Conversation:
    """A question and its follow-ups, answered in one window."""

    __slots__ = ("messages", "settings", "window")

    def __init__(self, settings: Settings, first: Sequence[Part], title: str, desktop: Desktop, submit: Callable[[Callable[[], None]], None]) -> None:
        self.settings = settings
        self.messages: tuple[Message, ...] = (system_message(prompts.ASK), user_message(first))
        self.window = desktop.answer(title, lambda question: submit(lambda: self.follow_up(question)))

    def run(self) -> Failure | Outcome:
        result = stream(self.settings, self.messages, self.window.write)
        if isinstance(result, Failure):
            self.window.fail(result.message)
            return result
        self.messages = (*self.messages, assistant_message(result))
        self.window.finish()
        return Outcome.DONE

    def follow_up(self, question: str) -> None:
        self.messages = (*self.messages, user_message(question))
        self.run()


class Assistant:
    """Turns requests from the layout's tool and app keys into actions."""

    __slots__ = (
        "capture",
        "capture_id",
        "desktop",
        "latest_transcription",
        "layout_on",
        "missing",
        "record",
        "run_agent",
        "settings",
        "show_agent",
        "stop_agent",
        "submit",
    )

    def __init__(
        self,
        desktop: Desktop,
        settings: Settings,
        *,
        record: Recorder,
        submit: Callable[[Callable[[], None]], None],
        run_agent: Callable[[str], None],
        show_agent: Callable[[], None],
        stop_agent: Callable[[], None],
        missing: Missing | None = None,
    ) -> None:
        self.desktop = desktop
        self.settings = settings
        self.record = record
        self.submit = submit
        """Runs a job on the worker thread, after whatever is already queued."""
        self.run_agent = run_agent
        self.show_agent = show_agent
        self.stop_agent = stop_agent
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

    def handle(self, request: Request, *, down: bool) -> None:
        """A tool or app key went down or up. Returns quickly; slow work is submitted."""
        if self.missing is not None and isinstance(request, Tool) and request not in LOCAL_TOOLS:
            if down:
                self.desktop.problem(f"Set {', '.join(self.missing.names)} to use the AI tools (see the README).")
            return
        match request:
            case App():
                if down:
                    self.timed(f"app:{request.name}", lambda: self.switch_to(request))
            case Tool.STOP:
                if down:
                    if self.listening is not None:
                        self.stop_capture(reason="stop")
                    else:
                        self.stop_agent()
            case Tool.AGENT_VOICE_TOGGLE | Tool.DICTATE_TOGGLE:
                if down:
                    if self.listening is not None:
                        self.stop_capture(reason="toggle")
                    else:
                        self.hold(request, down=True)
            case Tool.COPY_TRANSCRIPT:
                if down:
                    self.submit(self.copy_transcript)
            case Tool() if request in HOLD_TOOLS:
                self.hold(request, down=down)
            case Tool() if request in WINDOW_TOOLS:
                if down:
                    self.submit(lambda: self.timed(request.name.lower(), lambda: self.arrange(request)))
            case Tool():
                if down:
                    self.submit(lambda: self.timed(request.name.lower(), lambda: self.act(request)))

    def idle(self) -> None:
        self.desktop.show_state(State.READY if self.layout_on else State.LAYOUT_OFF)

    def timed(self, feature: str, job: Callable[[], Failure | Outcome], *, extra: Mapping[str, Detail] | None = None) -> None:
        """Runs a job, reports a failure, and logs the use (never the content)."""
        started = time.monotonic()
        outcome: Failure | Outcome = Failure("crashed")
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
            elif outcome is Outcome.CANCELLED:
                details["cancelled"] = True
            self.record(feature, details)
            if self.listening is None:
                self.idle()

    def hold(self, tool: Tool, *, down: bool) -> None:
        if down:
            if self.capture is not None:
                return
            self.capture_id += 1
            capture = Capture(self.capture_id, tool, voice_tool(tool), time.monotonic())
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
        self.desktop.show_state(State.WORKING)
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

    def heard(self, tool: Tool, pcm: bytes, details: dict[str, Detail]) -> Failure | Outcome:
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
            case Tool.REWRITE_VOICE:
                details["phase"] = "rewriting"
                return self.rewrite(transcript)
            case Tool.AGENT_VOICE:
                submit_voice_text(transcript, self.run_agent, details)
            case _:
                raise AssertionError(f"{tool} doesn't listen")
        return Outcome.DONE

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

    def arrange(self, tool: Tool) -> Failure | Outcome:
        try:
            self.desktop.arrange(tool)
        except OSError as error:
            return Failure(str(error))
        return Outcome.DONE

    def act(self, tool: Tool) -> Failure | Outcome:
        if tool in REWRITES:
            return self.rewrite(REWRITES[tool])
        match tool:
            case Tool.ASK:
                return self.ask()
            case Tool.SCREEN_TEXT:
                return self.screen_text()
            case Tool.SCREEN_ASK:
                return self.screen_ask()
            case Tool.AGENT_TYPED:
                self.show_agent()
                return Outcome.DONE
            case _:
                raise AssertionError(f"{tool} isn't a tool that acts on press")

    def rewrite(self, instruction: str) -> Failure | Outcome:
        self.desktop.show_state(State.WORKING)
        if not (text := self.desktop.copy_selection()):
            return Failure("Select some text first.")
        if isinstance(result := ask(self.settings, prompts.rewrite(instruction), text), Failure):
            return result
        self.desktop.paste(unwrap(result))
        return Outcome.DONE

    def ask(self) -> Failure | Outcome:
        selection = self.desktop.copy_selection()
        if not (question := self.desktop.prompt("Ask")):
            return Outcome.CANCELLED
        self.desktop.show_state(State.WORKING)
        content = f"{question}\n\nSelected text:\n{selection}" if selection else question
        return Conversation(self.settings, [Text(content)], question, self.desktop, self.submit).run()

    def screenshot(self) -> bytes | None:
        area = self.desktop.choose_region()
        return None if area is None else self.desktop.capture(area, SCREENSHOT_SIZE)[0]

    def screen_text(self) -> Failure | Outcome:
        if (png := self.screenshot()) is None:
            return Outcome.CANCELLED
        self.desktop.show_state(State.WORKING)
        if isinstance(result := ask(self.settings, prompts.SCREEN_TEXT, [Image(png)]), Failure):
            return result
        text = unwrap(result)
        self.desktop.set_clipboard(text)
        self.desktop.notify("Text copied", " ".join(text.split())[:80])
        return Outcome.DONE

    def screen_ask(self) -> Failure | Outcome:
        if (png := self.screenshot()) is None:
            return Outcome.CANCELLED
        if (question := self.desktop.prompt("Ask about this (Enter: explain it)")) is None:
            return Outcome.CANCELLED
        self.desktop.show_state(State.WORKING)
        question = question or prompts.SCREEN_QUESTION
        return Conversation(self.settings, [Text(question), Image(png)], question, self.desktop, self.submit).run()

    def switch_to(self, app: App) -> Failure | Outcome:
        foreground = self.desktop.foreground()
        handle = pick_window(self.desktop.windows(), app, foreground)
        if handle is None:
            self.desktop.launch(app.command)
        elif handle != foreground and not self.desktop.focus(handle):
            return Failure(f"Windows wouldn't bring {app.name} to the front.")
        return Outcome.DONE
