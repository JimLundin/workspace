"""Native meeting events and conversations, independent of capture and canvas effects."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, TypeAdapter

from automation.capture import AudioSource

type Timestamp = Annotated[float, Field(ge=0, allow_inf_nan=False)]
type Seconds = Annotated[float, Field(ge=0, allow_inf_nan=False)]


@dataclass(frozen=True, slots=True)
class InProgress:
    started_at: Timestamp
    kind: Literal["in_progress"] = "in_progress"


@dataclass(frozen=True, slots=True)
class Ended:
    started_at: Timestamp
    ended_at: Timestamp
    kind: Literal["ended"] = "ended"

    def __post_init__(self) -> None:
        if self.ended_at < self.started_at:
            raise ValueError("A meeting cannot end before it starts.")


@dataclass(frozen=True, slots=True)
class UnknownEnd:
    """Capture ended without an observed wall-clock end, for example after a crash."""

    started_at: Timestamp
    kind: Literal["unknown_end"] = "unknown_end"


type MeetingPeriod = Annotated[InProgress | Ended | UnknownEnd, Field(discriminator="kind")]


class TranscriptState(StrEnum):
    PENDING = "pending"
    COMPLETE = "complete"


@dataclass(frozen=True, slots=True)
class Meeting:
    """One cohesive event observation: identity, timing, audio coverage and transcript state."""

    identity: Annotated[str, StringConstraints(min_length=1, max_length=500)]
    title: Annotated[str, StringConstraints(min_length=1, max_length=240)]
    period: MeetingPeriod
    audio_source: AudioSource
    captured_seconds: Seconds
    pending_seconds: Seconds
    transcript_path: Annotated[str, StringConstraints(min_length=1, max_length=4000)]
    transcript_state: TranscriptState
    revision: Annotated[int, Field(strict=True, ge=0)]
    problem: str = ""

    def __post_init__(self) -> None:
        if self.pending_seconds > self.captured_seconds:
            raise ValueError("Pending transcription exceeds captured meeting audio.")


@dataclass(frozen=True, slots=True)
class TranscriptEntry:
    """One transcription batch on the captured-audio timeline, not a speaker turn."""

    start_seconds: Seconds
    end_seconds: Seconds
    text: str
    speaker: Literal["unknown"] = "unknown"

    def __post_init__(self) -> None:
        if self.end_seconds <= self.start_seconds:
            raise ValueError("A transcript entry requires a positive time span.")


@dataclass(frozen=True, slots=True)
class MeetingConversation:
    meeting: Meeting
    entries: tuple[TranscriptEntry, ...]
    total: int
    next_offset: int | None
    kind: Literal["meeting_conversation"] = "meeting_conversation"


MEETING = TypeAdapter(Meeting)
CONVERSATION = TypeAdapter(MeetingConversation)
