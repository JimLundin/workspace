"""The messages between the desktop and the assistant survive the wire exactly."""

from contracts.desktop_link import (
    JobChanged,
    MicLevel,
    Notify,
    Record,
    RecordingChanged,
    ToAssistant,
    ToDesktop,
    UseTool,
    VoiceChanged,
    WireError,
    from_assistant,
    from_desktop,
    state_key,
    to_assistant,
    to_desktop,
)
from contracts.recording_state import RecordingState
from contracts.status import Job, State
from protocol import Tool


def test_every_message_survives_the_wire_exactly() -> None:
    # Defect: a message (or a value inside one: an enum, an optional, a nested
    # state) changes or fails on its way between the processes.
    to_the_desktop: tuple[ToDesktop, ...] = (
        VoiceChanged(State.LISTENING),
        JobChanged(Job.TRANSCRIBING),
        JobChanged(None),
        RecordingChanged(RecordingState(phase="recording", seconds=12)),
        MicLevel(0.4),
        Notify("Workspace", "The microphone is busy.", warning=True),
    )
    for message in to_the_desktop:
        assert from_assistant(to_desktop(message)) == message, message
    to_the_assistant: tuple[ToAssistant, ...] = (UseTool(Tool.MEETING_TOGGLE), Record("start"))
    for command in to_the_assistant:
        assert from_desktop(to_assistant(command)) == command, command


def test_a_frame_from_the_wrong_direction_or_a_broken_peer_is_refused() -> None:
    # Defect: a frame meant for the other side, or a garbled one, is acted on as
    # some message instead of being refused.
    for frame in (to_assistant(Record("stop")), b"Nonsense\n{}", b"VoiceChanged\n{not json", b""):
        try:
            from_assistant(frame)
        except WireError:
            continue
        raise AssertionError(f"{frame!r} was accepted.")


def test_only_states_are_kept_and_replayed() -> None:
    # Defect: an event (a notification) is replayed to every desktop that connects,
    # or a state isn't, so a restarted desktop shows nothing current.
    assert state_key(RecordingChanged(RecordingState())) == "RecordingChanged"
    assert state_key(Notify("Workspace", "Done")) is None
    assert state_key(JobChanged(None)) != state_key(VoiceChanged(State.READY))
