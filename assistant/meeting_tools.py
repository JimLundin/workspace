"""The meeting tool family: capture by voice."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

from pydantic import ConfigDict, TypeAdapter

from assistant.agent_tools import NO_ARGUMENTS, Args, Display, Output, Session, Tool, argument_spec, fixed, typed_run
from assistant.llm import ToolSpec
from automation.actions import Change, Evidence, Observation
from automation.capture import AudioSource
from automation.ipc import MeetingCommand, MeetingOperation, StartMeeting


@dataclass(frozen=True, slots=True)
class CaptureArguments:
    """meeting_start's source and title; the other capture tools take neither."""

    source: AudioSource = "both"
    title: str = "Meeting"
    __pydantic_config__ = ConfigDict(strict=True)


_CAPTURE = TypeAdapter(CaptureArguments)


CAPTURE_SPECS: Final = (
    argument_spec(
        "meeting_start",
        "Start a long meeting transcript when the user asks to record or transcribe a meeting. "
        "source=both includes the microphone and default computer playback, including remote participants; "
        "source=microphone records only the room. Text is saved progressively; audio is deleted after transcription. "
        "Capture continues until meeting_stop or Workspace exits, independently of this agent task.",
        _CAPTURE,
    ),
    argument_spec("meeting_stop", "Stop meeting capture and finish the pending transcript. Does not discard saved audio or text.", NO_ARGUMENTS),
    argument_spec("meeting_status", "Get recording state, elapsed time, pending audio duration and the local transcript path.", NO_ARGUMENTS),
    argument_spec("meeting_list", "List recent saved meeting transcript paths. Read the requested transcript before summarizing it.", NO_ARGUMENTS),
    argument_spec("meeting_retry", "Retry pending transcription from the local journal without starting audio capture.", NO_ARGUMENTS),
)


def _capture_tool(spec: ToolSpec, run: Callable[[Args, CaptureArguments], Output]) -> Tool:
    # Only meeting_start takes arguments; the other capture tools take none.
    match spec.name:
        case "meeting_start":
            capture = typed_run(_CAPTURE, run)
        case _:
            capture = typed_run(NO_ARGUMENTS, lambda args, _none: run(args, CaptureArguments()))
    match spec.name:
        case "meeting_status":
            return Tool(spec, capture, fixed(Observation(("meeting",))), Display.PRIVATE)
        case "meeting_list":
            return Tool(spec, capture, fixed(Observation(("meeting",), Evidence.GENERAL)), Display.PRIVATE)
        case "meeting_start" | "meeting_stop" | "meeting_retry":
            return Tool(spec, capture, fixed(Change(("meeting",))), Display.PRIVATE)
        case _:
            raise ValueError(f"The meeting tool {spec.name} has no classification.")


def _operation(name: str, request: CaptureArguments) -> MeetingOperation:
    match name:
        case "meeting_start":
            return StartMeeting(request.source, request.title)
        case "meeting_stop":
            return MeetingCommand.STOP
        case "meeting_retry":
            return MeetingCommand.RETRY
        case "meeting_list":
            return MeetingCommand.LIST
        case "meeting_status":
            return MeetingCommand.STATUS
        case _:
            raise ValueError(f"The meeting tool {name} has no operation.")


class MeetingCapture:
    __slots__ = ("session",)

    def __init__(self, session: Session) -> None:
        self.session = session

    def tools(self) -> tuple[Tool, ...]:
        return tuple(_capture_tool(spec, self.capture) for spec in CAPTURE_SPECS)

    def capture(self, args: Args, request: CaptureArguments) -> Output:
        operation = _operation(args.tool, request)
        return self.session.effect(args.operation, lambda: Output(self.session.machine.meeting(operation)))
