"""Workspace's packet boundaries and packet timing must not alter converted audio, sample clocks or the recording's continuity."""

from array import array
from dataclasses import dataclass
from itertools import pairwise

from hypothesis import strategies

from tests.properties.generation import cases, property_test
from winapi.pcm import RATE, Converter, LateAudio, Mixer, PcmFormat, Skipped


@dataclass(frozen=True, slots=True)
class AudioCase:
    format: PcmFormat
    pcm: bytes
    packets: tuple[bytes, ...]


def audio_cases(draw: strategies.DrawFn) -> AudioCase:
    rate = draw(strategies.one_of(strategies.sampled_from((8_000, RATE, 44_100, 48_000, 384_000)), strategies.integers(8_000, 384_000)))
    channels = draw(strategies.integers(1, 8))
    bits, floating = draw(strategies.sampled_from(((16, False), (24, False), (32, False), (32, True))))
    format = PcmFormat(rate, channels, bits, floating=floating)
    frames = draw(strategies.integers(0, 64))
    count = frames * channels
    if floating:
        samples = tuple(draw(strategies.lists(strategies.floats(-2, 2, width=32), min_size=count, max_size=count)))
        pcm = array("f", samples).tobytes()
    else:
        limit = 1 << (bits - 1)
        integers = tuple(draw(strategies.lists(strategies.integers(-limit, limit - 1), min_size=count, max_size=count)))
        pcm = b"".join(sample.to_bytes(bits // 8, "little", signed=True) for sample in integers)
    # Duplicate cuts include empty packets; every cut remains on a whole frame.
    cuts = tuple(sorted(draw(strategies.lists(strategies.integers(0, frames), max_size=16))))
    packets = tuple(pcm[start * format.frame_bytes : end * format.frame_bytes] for start, end in pairwise((0, *cuts, frames)))
    return AudioCase(format, pcm, packets)


@property_test(cases(audio_cases))
def test_packet_partition_preserves_audio_and_sample_clocks(case: AudioCase) -> None:
    whole = Converter(case.format)
    expected = whole.convert(case.pcm)
    fragmented = Converter(case.format)
    actual = b"".join(fragmented.convert(packet) for packet in case.packets)
    assert actual == expected
    frames = len(case.pcm) // case.format.frame_bytes
    assert fragmented.input_frames == whole.input_frames == frames
    assert fragmented.output_frames == whole.output_frames == len(actual) // 2
    assert abs(fragmented.output_frames - frames * RATE / case.format.rate) <= 2


@dataclass(frozen=True, slots=True)
class Packet:
    """A device packet placed `offset` frames from the published cursor; each sample is `value`."""

    offset: int
    length: int
    value: int


@dataclass(frozen=True, slots=True)
class Publish:
    """A take `ahead` frames past the published cursor."""

    ahead: int


@dataclass(frozen=True, slots=True)
class TimingCase:
    capacity: int
    steps: tuple[Packet | Publish, ...]


def timing_cases(draw: strategies.DrawFn) -> TimingCase:
    capacity = draw(strategies.integers(2, 48))
    steps: list[Packet | Publish] = []
    for _ in range(draw(strategies.integers(0, 30))):
        if draw(strategies.booleans()):
            offset = draw(strategies.integers(-2 * capacity, 3 * capacity))
            steps.append(Packet(offset, draw(strategies.integers(1, capacity + 4)), draw(strategies.integers(1, 100))))
        else:
            steps.append(Publish(draw(strategies.integers(0, 3 * capacity))))
    return TimingCase(capacity, tuple(steps))


@property_test(cases(timing_cases))
def test_late_and_early_packets_cost_only_their_reported_gaps(case: TimingCase) -> None:
    # Defects: a late or early packet ends the recording; clipping a late packet
    # drops more than the part already published; pushing the cursor forward
    # republishes, reorders or loses buffered audio; a gap is unreported,
    # misplaced, mismeasured or reported for audio that was kept.
    mixer = Mixer(capacity=case.capacity, limit=8 * case.capacity)
    output = array("h", mixer.take(1))
    expected: dict[int, int] = {}
    end = 0
    for step in case.steps:
        before = mixer.cursor
        quiet_from = max(before, end)
        match step:
            case Packet(offset, length, value):
                start = before + offset
                mixer.add(start, array("h", [value] * length).tobytes())
                assert mixer.cursor == max(before, start + length - case.capacity), "The cursor moved further than the packet needed."
                kept = range(max(start, mixer.cursor), start + length)
                dropped = length - len(kept)
                silence = mixer.cursor - quiet_from
                gaps = mixer.reported()
                late = (LateAudio(start, dropped),) if dropped > 1 else ()
                assert gaps == ((Skipped(quiet_from, silence),) if silence > 0 else ()) + late
                for frame in kept:
                    expected[frame] = expected.get(frame, 0) + value
                if kept:
                    end = max(end, start + length)
            case Publish(ahead):
                output.extend(array("h", mixer.take(before + ahead)))
                stalled = ahead > case.capacity
                assert mixer.reported() == ((Skipped(quiet_from, before + ahead - quiet_from),) if stalled else ())
    output.extend(array("h", mixer.take(mixer.cursor + case.capacity)))
    assert not mixer.reported(), "Flushing exactly one ring reported a gap."
    assert len(output) == mixer.cursor, "Published frames do not match the published clock."
    assert output.tolist() == [expected.get(frame, 0) for frame in range(len(output))]
