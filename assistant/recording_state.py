"""Recording values and decisions, independent of devices, storage, threads, and widgets."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum, auto
from math import isfinite
from typing import Literal, assert_never

from automation.capture import AudioSource
from winapi.pcm import RATE, Dropout, LateAudio, Problem, Skipped, Stall

type Phase = Literal["idle", "starting", "recording", "stopping", "finishing", "paused", "saved", "interrupted"]
type RecordingAction = Literal["start", "stop", "open", "folder", "retry", "automatic"]
type CompletionPhase = Literal["finishing", "interrupted", "saved"]


class Exhausted(Enum):
    PAUSED = auto()


@dataclass(frozen=True, slots=True)
class Retry:
    failures: int
    delay: float


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    delays: tuple[float, ...] = (2, 4, 8, 16, 30)
    finished_attempts: int = 3

    def __post_init__(self) -> None:
        if not self.delays or any(not isfinite(delay) or delay < 0 for delay in self.delays) or self.finished_attempts < 1:
            raise ValueError("Retries need finite, nonnegative delays and at least one attempt.")

    def failed(self, failures: int, *, finished: bool) -> Retry | Exhausted:
        failures += 1
        if finished and failures >= self.finished_attempts:
            return Exhausted.PAUSED
        return Retry(failures, self.delays[min(failures - 1, len(self.delays) - 1)])


@dataclass(frozen=True, slots=True)
class RecordingState:
    """The view's progress snapshot; a starting capture may not yet have a journal."""

    phase: Phase = "idle"
    identity: str = ""
    title: str = "Meeting"
    source: AudioSource = "both"
    seconds: float = 0
    pending_seconds: float = 0
    path: str = ""
    detail: str = ""
    preview: str = ""
    revision: int = -1
    exported_revision: int = -1

    @property
    def capturing(self) -> bool:
        return self.phase in ("starting", "recording", "stopping")

    @property
    def visible(self) -> bool:
        return self.phase != "idle"


@dataclass(frozen=True, slots=True)
class StoredState:
    title: str
    source: AudioSource
    started: float
    frames: int
    pending: int
    finished: bool = field(kw_only=True)
    problem: str
    revision: int
    exported_revision: int
    ended_at: float | None = field(default=None, kw_only=True)
    gaps: int = field(default=0, kw_only=True)
    """Recovered capture timing problems: late audio clipped, or silence where capture fell behind."""
    gap_frames: int = field(default=0, kw_only=True)

    @property
    def gap_note(self) -> str:
        if not self.gaps:
            return ""
        plural = "gap" if self.gaps == 1 else "gaps"
        return (
            f"Recording continued through {self.gaps} {plural} totalling {self.gap_frames / RATE:.1f} s "
            "where audio arrived late or capture fell behind; that audio is missing from the transcript."
        )

    @property
    def export_current(self) -> bool:
        """Every captured frame is transcribed and Markdown has the latest revision."""
        return not self.pending and self.revision == self.exported_revision

    @property
    def complete(self) -> bool:
        """Capture finished and its current transcript is published."""
        return self.finished and self.export_current


@dataclass(frozen=True, slots=True)
class Batch:
    start: int
    pcm: bytes
    context: str = ""

    @property
    def end(self) -> int:
        return self.start + len(self.pcm) // 2


@dataclass(frozen=True, slots=True)
class Publication:
    identity: str
    path: str
    saved: StoredState
    preview: str


def completion_phase(saved: StoredState) -> CompletionPhase:
    """Decide progress after capture finishes, unless an explicit pause overrides it."""
    match saved:
        case StoredState() if not saved.export_current:
            return "finishing"
        case StoredState(problem=problem) if problem:
            return "interrupted"
        case _:
            return "saved"


def published(  # noqa: PLR0913 - one transition with its optional overrides
    current: RecordingState,
    incoming: Publication,
    *,
    stopping: bool,
    paused: str | None = None,
    phase: Phase | None = None,
    detail: str | None = None,
) -> RecordingState | None:
    """Reject stale observations before deriving the next immutable view snapshot."""
    saved = incoming.saved
    if current.phase == "starting" and not current.identity:
        return None  # a new capture reserved the view before its journal exists
    if current.identity and current.identity != incoming.identity:
        return None
    if (
        (saved.revision, saved.exported_revision) < (current.revision, current.exported_revision)
        or saved.frames < round(current.seconds * RATE)
        or saved.frames - saved.pending < round((current.seconds - current.pending_seconds) * RATE)
        or (not saved.finished and current.phase in ("finishing", "paused", "saved", "interrupted"))
    ):
        return None
    if not saved.finished:
        phase = "stopping" if stopping else "starting" if current.phase == "starting" else "recording"
    elif paused is not None:
        phase, detail = "paused", paused
    elif phase is None:
        phase = completion_phase(saved)
    return RecordingState(
        phase,
        incoming.identity,
        saved.title,
        saved.source,
        saved.frames / RATE,
        saved.pending / RATE,
        incoming.path,
        saved.problem or (detail if detail is not None else current.detail),
        incoming.preview,
        saved.revision,
        saved.exported_revision,
    )


@dataclass(frozen=True, slots=True)
class CaptureReport:
    """Recovered capture problems: the gaps they add to the recording and one log line."""

    gaps: int
    gap_frames: int
    text: str


def capture_report(problems: Sequence[Problem]) -> CaptureReport:
    stalls: list[float] = []
    gaps: dict[str, list[int]] = {}
    for problem in problems:
        match problem:
            case Stall(seconds=seconds):
                stalls.append(seconds)
            case LateAudio(frames=frames):
                gaps.setdefault("late audio clipped (it arrived after its time was saved)", []).append(frames)
            case Skipped(frames=frames):
                gaps.setdefault("silence inserted (capture fell further behind than the mixing ring)", []).append(frames)
            case Dropout(frames=frames):
                gaps.setdefault("microphone audio lost before it was read (its engine buffer overflowed)", []).append(frames)
            case _:
                assert_never(problem)
    parts = [f"capture loop stalled {len(stalls)}x, longest {max(stalls):.1f} s"] if stalls else []
    parts.extend(f"{label} {len(frames)}x, {sum(frames) * 1000 // RATE} ms" for label, frames in gaps.items())
    return CaptureReport(
        sum(map(len, gaps.values())),
        sum(map(sum, gaps.values())),
        "Meeting capture recovered: " + "; ".join(parts) + ".",
    )


def duration(seconds: float) -> str:
    hours, rest = divmod(max(0, int(seconds)), 3600)
    minutes, seconds = divmod(rest, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02}"


def source_name(source: AudioSource) -> str:
    match source:
        case "both":
            return "Microphone + computer audio"
        case "microphone":
            return "Microphone"
        case _:
            assert_never(source)
