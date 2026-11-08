"""Native meeting captions and conversation text from immutable journal observations."""

from datetime import datetime
from typing import assert_never

from contracts.meetings import Ended, InProgress, Meeting, MeetingConversation, TranscriptState, UnknownEnd
from contracts.recording_state import SOURCE_NAMES, duration


def time_range(meeting: Meeting) -> str:
    start = datetime.fromtimestamp(meeting.period.started_at).astimezone().isoformat(timespec="seconds")
    match meeting.period:
        case InProgress():
            return start + " · Recording"
        case Ended(ended_at=end):
            return start + " → " + datetime.fromtimestamp(end).astimezone().isoformat(timespec="seconds")
        case UnknownEnd():
            return start + " · End time unknown"
        case _:
            assert_never(meeting.period)


def meeting_text(conversation: MeetingConversation) -> str:
    meeting = conversation.meeting
    progress = "Transcript complete" if meeting.transcript_state is TranscriptState.COMPLETE else "Transcription pending"
    header = (
        f"{time_range(meeting)}\n{SOURCE_NAMES[meeting.audio_source]}\n"
        f"{duration(meeting.captured_seconds)} captured · {progress}\n"
        "Times below are captured-audio offsets. Speakers have not been identified."
    )
    entries = "\n\n".join(f"{duration(entry.start_seconds)} - {duration(entry.end_seconds)}\n{entry.text}" for entry in conversation.entries)
    if not entries:
        entries = "No conversation text yet." if meeting.transcript_state is TranscriptState.PENDING else "No speech was transcribed."
    return header + ("\n\n" + meeting.problem if meeting.problem else "") + "\n\n" + entries
