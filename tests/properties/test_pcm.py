"""Workspace's packet boundaries must not alter converted audio or sample clocks."""

from array import array
from dataclasses import dataclass
from itertools import pairwise

from hypothesis import strategies as st

from assistant.llm import RATE
from assistant.pcm import Converter, PcmFormat

from .generation import cases, property_test


@dataclass(frozen=True, slots=True)
class AudioCase:
    format: PcmFormat
    pcm: bytes
    packets: tuple[bytes, ...]


def audio_cases(draw: st.DrawFn) -> AudioCase:
    rate = draw(st.one_of(st.sampled_from((8_000, RATE, 44_100, 48_000, 384_000)), st.integers(8_000, 384_000)))
    channels = draw(st.integers(1, 8))
    bits, floating = draw(st.sampled_from(((16, False), (24, False), (32, False), (32, True))))
    format = PcmFormat(rate, channels, bits, floating)
    frames = draw(st.integers(0, 64))
    count = frames * channels
    if floating:
        samples = tuple(draw(st.lists(st.floats(-2, 2, width=32), min_size=count, max_size=count)))
        pcm = array("f", samples).tobytes()
    else:
        limit = 1 << (bits - 1)
        integers = tuple(draw(st.lists(st.integers(-limit, limit - 1), min_size=count, max_size=count)))
        pcm = b"".join(sample.to_bytes(bits // 8, "little", signed=True) for sample in integers)
    # Duplicate cuts include empty packets; every cut remains on a whole frame.
    cuts = tuple(sorted(draw(st.lists(st.integers(0, frames), max_size=16))))
    packets = tuple(pcm[start * format.frame_bytes:end * format.frame_bytes] for start, end in pairwise((0, *cuts, frames)))
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
