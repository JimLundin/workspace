"""Bounded PCM conversion and mixing for continuous, clock-aligned recording."""

import math
from array import array
from dataclasses import dataclass, field
from typing import Final

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


class Converter:
    """Downmix native packets and resample with one carried sample, without drift.

    Positions use integer ratios, so packet boundaries and hours of elapsed time
    cannot accumulate rounding error. WASAPI supplies little-endian Windows PCM.
    """

    __slots__ = ("format", "input_frames", "last", "output_frames")

    def __init__(self, format: PcmFormat) -> None:
        self.format = format
        self.input_frames = self.output_frames = 0
        self.last = 0.0

    def convert(self, pcm: bytes) -> bytes:
        format = self.format
        if len(pcm) % format.frame_bytes:
            raise ValueError("The audio packet ended inside a sample.")
        if not pcm:
            return b""
        if format == PcmFormat(RATE, 1, 16):
            self.input_frames += len(pcm) // 2
            self.output_frames += len(pcm) // 2
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
        beginning = self.input_frames
        if beginning:
            mono.insert(0, self.last)
            beginning -= 1
        self.input_frames += len(pcm) // format.frame_bytes
        self.last = mono[-1]
        result = array("h")
        while True:
            index, fraction = divmod(self.output_frames * format.rate, RATE)
            local = index - beginning
            if local >= len(mono) or (fraction and local + 1 >= len(mono)):
                break
            sample = mono[local]
            if fraction:
                sample += (mono[local + 1] - sample) * fraction / RATE
            result.append(max(-32768, min(32767, round(sample))))
            self.output_frames += 1
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


class Mixer:
    """A bounded ring on the shared device clock; absent playback is silence.

    The mixer recovers rather than failing: audio that arrives after its time
    was published loses only the part already published, and a device far
    ahead of the cursor pushes it forward, publishing what the ring holds and
    silence for the rest. Each recovery is a reported gap.
    """

    __slots__ = ("cursor", "end", "gaps", "limit", "ready", "samples")

    def __init__(self, capacity: int = CAPACITY, limit: int = MAX_JUMP) -> None:
        self.samples = array("i", [0]) * capacity
        self.limit = limit
        self.cursor = self.end = 0
        self.ready = array("h")
        self.gaps: list[Gap] = []

    def add(self, start: int, pcm: bytes) -> None:
        samples = array("h", pcm)
        # Idle WASAPI playback can timestamp silence from its last active
        # clock. Zero contributions cannot alter published or buffered audio;
        # ignore them before timing checks, while still accounting for late speech.
        if not any(samples):
            return
        placement = place(self.cursor, self.end, start, len(samples), len(self.samples))
        if placement.cursor > self.cursor:
            silence_at = max(self.cursor, self.end)
            self._publish(placement.cursor)
            if placement.silence:
                self.gaps.append(Skipped(silence_at, placement.silence))
        # One overlapping sample is packet-boundary rounding, not lost audio;
        # before the first take, audio timestamped before Start is not part of the recording.
        if placement.clipped > 1 and self.cursor:
            self.gaps.append(LateAudio(start, placement.clipped))
        for index in range(placement.clipped, len(samples)):
            self.samples[(start + index) % len(self.samples)] += samples[index]
        if placement.clipped < len(samples):
            self.end = max(self.end, start + len(samples))

    def take(self, until: int) -> bytes:
        until = max(self.cursor, until)
        if silence := jump(self.cursor, self.end, until, len(self.samples)):
            self.gaps.append(Skipped(max(self.cursor, self.end), silence))
        self._publish(until)
        result = self.ready.tobytes()
        self.ready = array("h")
        return result

    def reported(self) -> tuple[Gap, ...]:
        gaps = tuple(self.gaps)
        self.gaps.clear()
        return gaps

    def _publish(self, until: int) -> None:
        if until - self.cursor > self.limit:
            raise OSError(
                f"Recording stopped: the audio clock jumped {(until - self.cursor) / RATE:.0f} s, possibly during sleep. "
                "The captured part has been saved."
            )
        capacity = len(self.samples)
        for frame in range(self.cursor, min(until, self.cursor + capacity)):
            index = frame % capacity
            self.ready.append(max(-32768, min(32767, self.samples[index])))
            self.samples[index] = 0
        if until > self.cursor + capacity:
            self.ready.extend(array("h", bytes(2 * (until - self.cursor - capacity))))
        self.cursor = until


def quiet_tail(pcm: bytes) -> bool:
    """Prefer a half-second pause near a chunk boundary, without omitting speech."""
    return all(abs(sample) < 240 for sample in array("h", pcm[-RATE:]))
