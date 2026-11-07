"""Bounded PCM conversion and mixing for continuous, clock-aligned recording."""

import math
from array import array
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import Final

from cell import Cell

RATE: Final = 16_000
"""Samples per second Workspace records and sends. Speech models work at 16 kHz; more only makes uploads bigger."""


@dataclass(frozen=True, slots=True)
class PcmFormat:
    rate: int
    channels: int
    bits: int
    floating: bool = field(default=False, kw_only=True)

    def __post_init__(self) -> None:
        if not 8_000 <= self.rate <= 384_000 or not 1 <= self.channels <= 8:
            raise ValueError("Unsupported audio sample rate or channel count.")
        if self.bits not in ((32,) if self.floating else (16, 24, 32)):
            raise ValueError("Unsupported audio sample format.")

    @property
    def frame_bytes(self) -> int:
        return self.channels * (self.bits // 8)


@dataclass(frozen=True, slots=True)
class Position:
    """How far a conversion has read and written, and the sample it carries across packets."""

    input_frames: int = 0
    output_frames: int = 0
    last: float = 0.0


@dataclass(frozen=True, slots=True)
class Converter:
    """Downmix native packets and resample with one carried sample, without drift.

    Positions use integer ratios, so packet boundaries and hours of elapsed time
    cannot accumulate rounding error. WASAPI supplies little-endian Windows PCM.
    """

    format: PcmFormat
    _position: Cell[Position] = field(default_factory=lambda: Cell(Position()))

    @classmethod
    def at(cls, format: PcmFormat, position: Position) -> Converter:
        """A conversion continuing from `position`."""
        return cls(format, Cell(position))

    @property
    def position(self) -> Position:
        return self._position.get()

    def convert(self, pcm: bytes) -> bytes:
        format = self.format
        if len(pcm) % format.frame_bytes:
            raise ValueError("The audio packet ended inside a sample.")
        if not pcm:
            return b""
        position = self._position.get()
        if format == PcmFormat(RATE, 1, 16):
            frames = len(pcm) // 2
            self._position.set(replace(position, input_frames=position.input_frames + frames, output_frames=position.output_frames + frames))
            return pcm
        if format.bits == 24:
            samples = [float(int.from_bytes(pcm[i : i + 3], "little", signed=True)) / 256 for i in range(0, len(pcm), 3)]
        elif format.floating:
            samples = [float(value) * 32768 for value in array("f", pcm)]
        elif format.bits == 16:
            samples = [float(value) for value in array("h", pcm)]
        else:
            samples = [float(value) / 65536 for value in array("i", pcm)]
        if not all(math.isfinite(sample) for sample in samples):
            raise ValueError("The audio device returned a non-finite sample.")
        mono = [sum(samples[i : i + format.channels]) / format.channels for i in range(0, len(samples), format.channels)]
        beginning = position.input_frames
        if beginning:
            mono.insert(0, position.last)
            beginning -= 1
        output_frames = position.output_frames
        result = array("h")
        while True:
            index, fraction = divmod(output_frames * format.rate, RATE)
            local = index - beginning
            if local >= len(mono) or (fraction and local + 1 >= len(mono)):
                break
            sample = mono[local]
            if fraction:
                sample += (mono[local + 1] - sample) * fraction / RATE
            result.append(max(-32768, min(32767, round(sample))))
            output_frames += 1
        self._position.set(Position(position.input_frames + len(pcm) // format.frame_bytes, output_frames, mono[-1]))
        return result.tobytes()


CAPACITY: Final = RATE * 10
"""The mixer's ring: how far one device may run ahead of the published cursor before the cursor is pushed."""
MAX_JUMP: Final = RATE * 60
"""The longest silence the mixer inserts; a larger clock jump (sleep, a broken clock) ends the recording."""


@dataclass(frozen=True, slots=True)
class LateAudio:
    """A packet began before audio already published; its first `frames` were dropped."""

    at: int
    frames: int


@dataclass(frozen=True, slots=True)
class Skipped:
    """Capture fell further behind than the ring holds; `frames` of silence stand in for unheard audio."""

    at: int
    frames: int


@dataclass(frozen=True, slots=True)
class Dropout:
    """The microphone reported a discontinuity: `frames` it captured were lost before Workspace read them."""

    at: int
    frames: int


type Gap = LateAudio | Skipped | Dropout


@dataclass(frozen=True, slots=True)
class Stall:
    """The capture loop published nothing for `seconds` after frame `at`; any loss it caused is reported as a gap."""

    at: int
    seconds: float


type Problem = Gap | Stall
"""A capture timing problem the recording recovered from."""

DROPOUT_TOLERANCE: Final = RATE // 100
"""Timestamp rounding across a flagged discontinuity is not lost audio."""


def dropout(previous_end: int | None, start: int, *, discontinuous: bool) -> Dropout | None:
    """A continuous stream's flagged hole between its previous packet and this one."""
    if previous_end is None or not discontinuous or start - previous_end <= DROPOUT_TOLERANCE:
        return None
    return Dropout(previous_end, start - previous_end)


@dataclass(frozen=True, slots=True)
class Placement:
    """Where a packet goes on the ring, decided before any sample moves."""

    cursor: int
    """The published cursor after any forced advance."""
    clipped: int
    """Leading packet frames that precede that cursor."""
    silence: int
    """Frames of the forced advance after the last mixed audio."""


def place(cursor: int, end: int, start: int, length: int, capacity: int) -> Placement:
    """Push the cursor just far enough for the packet's end to fit, then clip what precedes it."""
    advanced = max(cursor, start + length - capacity)
    return Placement(advanced, min(length, max(0, advanced - start)), max(0, advanced - max(cursor, end)))


def jump(cursor: int, end: int, until: int, capacity: int) -> int:
    """Silent frames a take inserts beyond the ring, where no device delivered audio in time."""
    return until - max(cursor, end) if until - cursor > capacity else 0


@dataclass(frozen=True, slots=True)
class _Mixed:
    cursor: int = 0
    """The published clock: every frame before it has been taken or is waiting in `ready`."""
    end: int = 0
    """Just past the latest mixed audio."""
    ready: bytes = b""
    """Published audio not yet taken."""
    gaps: tuple[Gap, ...] = ()
    """Recoveries not yet reported."""


@dataclass(frozen=True, slots=True)
class Mixer:
    """A bounded ring on the shared device clock; absent playback is silence.

    The mixer recovers rather than failing: audio that arrives after its time
    was published loses only the part already published, and a device far
    ahead of the cursor pushes it forward, publishing what the ring holds and
    silence for the rest. Each recovery is a reported gap.

    The ring is the one buffer written in place: copying it for each packet
    would copy the whole ring every 10 ms. Everything else is one frozen record.
    """

    _samples: array[int]
    limit: int
    _mixed: Cell[_Mixed]

    @classmethod
    def ring(cls, capacity: int = CAPACITY, limit: int = MAX_JUMP, *, cursor: int = 0) -> Mixer:
        return cls(array("i", [0]) * capacity, limit, Cell(_Mixed(cursor, cursor)))

    @property
    def cursor(self) -> int:
        return self._mixed.get().cursor

    @property
    def samples(self) -> Sequence[int]:
        """The ring, for inspecting what it still holds."""
        return self._samples

    def add(self, start: int, pcm: bytes) -> None:
        samples = array("h", pcm)
        # Idle WASAPI playback can timestamp silence from its last active
        # clock. Zero contributions cannot alter published or buffered audio;
        # ignore them before timing checks, while still accounting for late speech.
        if not any(samples):
            return
        mixed = self._mixed.get()
        placement = place(mixed.cursor, mixed.end, start, len(samples), len(self._samples))
        if placement.cursor > mixed.cursor:
            silence_at = max(mixed.cursor, mixed.end)
            mixed = self._published(mixed, placement.cursor)
            if placement.silence:
                mixed = replace(mixed, gaps=(*mixed.gaps, Skipped(silence_at, placement.silence)))
        # One overlapping sample is packet-boundary rounding, not lost audio;
        # before the first take, audio timestamped before Start is not part of the recording.
        if placement.clipped > 1 and mixed.cursor:
            mixed = replace(mixed, gaps=(*mixed.gaps, LateAudio(start, placement.clipped)))
        for index in range(placement.clipped, len(samples)):
            self._samples[(start + index) % len(self._samples)] += samples[index]
        if placement.clipped < len(samples):
            mixed = replace(mixed, end=max(mixed.end, start + len(samples)))
        self._mixed.set(mixed)

    def take(self, until: int) -> bytes:
        mixed = self._mixed.get()
        until = max(mixed.cursor, until)
        if silence := jump(mixed.cursor, mixed.end, until, len(self._samples)):
            mixed = replace(mixed, gaps=(*mixed.gaps, Skipped(max(mixed.cursor, mixed.end), silence)))
        mixed = self._published(mixed, until)
        self._mixed.set(replace(mixed, ready=b""))
        return mixed.ready

    def reported(self) -> tuple[Gap, ...]:
        gaps = self._mixed.get().gaps
        self._mixed.update(lambda mixed: replace(mixed, gaps=()))
        return gaps

    def _published(self, mixed: _Mixed, until: int) -> _Mixed:
        """`mixed` with the ring published up to `until`, clearing the published part of the ring."""
        cursor = mixed.cursor
        if until - cursor > self.limit:
            raise OSError(
                f"Recording stopped: the audio clock jumped {(until - cursor) / RATE:.0f} s, possibly during sleep. The captured part has been saved."
            )
        capacity = len(self._samples)
        frames = range(cursor, min(until, cursor + capacity))
        published = array("h", (max(-32768, min(32767, self._samples[frame % capacity])) for frame in frames))
        for frame in frames:
            self._samples[frame % capacity] = 0
        silence = bytes(2 * max(0, until - cursor - capacity))
        return replace(mixed, cursor=until, ready=mixed.ready + published.tobytes() + silence)


def quiet_tail(pcm: bytes) -> bool:
    """Prefer a half-second pause near a chunk boundary, without omitting speech."""
    return all(abs(sample) < 240 for sample in array("h", pcm[-RATE:]))
