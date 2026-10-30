"""Only active work earns space in the desktop toolbar."""

from dataclasses import dataclass, field
from typing import Literal

from assistant.icons import State
from assistant.notifications import Tone
from assistant.recording_state import RecordingState


@dataclass(frozen=True, slots=True)
class Resting:
    tone: Tone = Tone.REPLY


@dataclass(frozen=True, slots=True)
class Activity:
    title: str
    icon: str
    tone: Tone
    can_stop: bool = field(default=False, kw_only=True)


@dataclass(frozen=True, slots=True)
class Capture:
    title: str
    action: Literal["stop", "open"]
    can_stop: bool = field(kw_only=True)


@dataclass(frozen=True, slots=True)
class Toolbar:
    activity: Activity | Resting
    capture: Capture | None
    keyboard: str | None


def toolbar(state: State, recording: RecordingState, *, enabled: bool, layer: str | None) -> Toolbar:
    activities: dict[State, Activity | Resting] = {
        State.READY: Resting(),
        State.LAYOUT_OFF: Resting(),
        State.LISTENING: Activity("Listening", "mic", Tone.USER, can_stop=True),
        State.WORKING: Activity("Transcribing", "refresh", Tone.THINKING),
        State.AGENT: Activity("Working", "agent", Tone.ACTION, can_stop=True),
        State.NEEDS_INPUT: Activity("Needs you", "chat", Tone.QUESTION),
        State.RECORDING: Resting(),
    }
    activity = activities[state]
    capture = None
    seconds = max(0, int(recording.seconds))
    match recording.phase:
        case "starting":
            capture = Capture("Starting…", "stop", can_stop=True)
        case "recording":
            capture = Capture(f"{seconds // 60:02}:{seconds % 60:02}", "stop", can_stop=True)
        case "stopping":
            capture = Capture("Stopping…", "open", can_stop=False)
        case "finishing":
            capture = Capture("Saving…", "open", can_stop=False)
        case "paused" | "interrupted":
            capture = Capture("Check recording", "open", can_stop=False)
        case "idle" | "saved":
            pass
    return Toolbar(activity, capture, "Colemak" if not enabled else layer)
