"""Only active work earns space in the desktop toolbar."""

from dataclasses import dataclass, field

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
    # What the bar's Stop control ends; None when this activity offers no Stop.
    stop: str | None = field(kw_only=True)


@dataclass(frozen=True, slots=True)
class Capture:
    # RecordingState.phase is the alternative; the capsule only needs its
    # caption and whether that phase can still be stopped.
    title: str
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
        State.LISTENING: Activity("Listening", "mic", Tone.USER, stop="Stop speech capture"),
        State.WORKING: Activity("Transcribing captured audio", "refresh", Tone.THINKING, stop=None),
        State.AGENT: Activity("Working", "agent", Tone.ACTION, stop="Stop agent work"),
        State.NEEDS_INPUT: Activity("Needs you", "chat", Tone.QUESTION, stop=None),
        State.RECORDING: Resting(),
    }
    activity = activities[state]
    capture = None
    seconds = max(0, int(recording.seconds))
    match recording.phase:
        case "starting":
            capture = Capture("Starting…", can_stop=True)
        case "recording":
            capture = Capture(f"{seconds // 60:02}:{seconds % 60:02}", can_stop=True)
        case "stopping":
            capture = Capture("Stopping…", can_stop=False)
        case "finishing":
            capture = Capture("Saving…", can_stop=False)
        case "paused" | "interrupted":
            capture = Capture("Check recording", can_stop=False)
        case "idle" | "saved":
            pass
    return Toolbar(activity, capture, "Colemak" if not enabled else layer)
