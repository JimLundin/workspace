"""Meeting capture over a fake WASAPI: clocks, mixing, dropouts and device cleanup."""

import ctypes
import threading
import unittest
from array import array
from ctypes import wintypes
from typing import cast

from winapi import audio, recording
from winapi.pcm import RATE, Dropout, Problem, Stall


def no_gap(problem: Problem) -> None:
    # Defect: on-time synthetic packets are misreported as late or skipped audio.
    raise AssertionError(f"An on-time capture reported a problem: {problem}")


def set_pointer(argument: object, value: int) -> None:
    ctypes.cast(cast("ctypes.c_void_p", argument), ctypes.POINTER(ctypes.c_void_p)).contents.value = value


def set_uint(argument: object, value: int) -> None:
    ctypes.cast(cast("ctypes.c_void_p", argument), ctypes.POINTER(wintypes.UINT)).contents.value = value


def set_u64(argument: object, value: int) -> None:
    ctypes.cast(cast("ctypes.c_void_p", argument), ctypes.POINTER(ctypes.c_ulonglong)).contents.value = value


class Wasapi:
    """Own the synthetic native buffers, packet cursors and capture clock."""

    __slots__ = (
        "buffer",
        "calls",
        "delivered",
        "discontinuous",
        "dropouts",
        "fail",
        "flags",
        "format",
        "lag",
        "microphone_positions",
        "now",
        "origin",
        "packet_frames",
        "stalls",
        "stop_at",
        "ticks",
    )

    def __init__(self) -> None:
        self.format = audio.WAVEFORMATEX(3, 2, 48_000, 48_000 * 8, 8, 32, 0)
        self.origin = self.now = 1000.0
        self.ticks, self.stop_at = 0, 127
        self.stalls: dict[int, float] = {}
        self.lag = 0.0
        self.delivered = {30: 0, 31: 0}
        self.dropouts: dict[tuple[int, int], int] = {}
        self.discontinuous: set[int] = set()
        self.packet_frames = 480
        self.microphone_positions: tuple[int, ...] = ()
        self.flags = 0
        self.buffer = ctypes.create_string_buffer(0)
        self.calls: list[tuple[int, int]] = []
        self.fail: tuple[int, int] | None = None

    def initialize(self) -> int:
        return 0

    def uninitialize(self) -> None:
        pass

    def create_enumerator(self, pointer: ctypes.c_void_p) -> int:
        pointer.value = 1
        return 0

    def free_format(self, pointer: ctypes.c_void_p) -> None:
        pass

    def clock(self) -> float:
        return self.now

    def wait(self, stop: threading.Event, timeout: float) -> bool:
        self.ticks += 1
        self.lag += self.stalls.get(self.ticks, 0)
        self.now = self.origin + self.ticks * timeout + self.lag
        return self.ticks >= self.stop_at

    def method(self, pointer: ctypes.c_void_p, index: int, *types: object) -> recording.NativeCall:
        handle = pointer.value
        assert handle is not None

        def invoke(*arguments: object) -> int:
            self.calls.append((handle, index))
            if (handle, index) == self.fail:
                return -2_002_000_001
            return self.invoke(handle, index, arguments)

        return invoke

    def invoke(self, handle: int, index: int, arguments: tuple[object, ...]) -> int:
        if index == 2:  # IUnknown.Release
            return 0
        if handle == 1 and index == 4:  # default endpoint: eRender=0, eCapture=1
            set_pointer(arguments[-1], 10 if arguments[1] == 1 else 11)
        elif handle in (10, 11) and index == 3:  # device.Activate
            set_pointer(arguments[-1], handle + 10)
        elif handle in (20, 21):
            if index == 8:  # client.GetMixFormat
                set_pointer(arguments[-1], ctypes.addressof(self.format))
            elif index == 14:  # client.GetService
                set_pointer(arguments[-1], handle + 10)
            elif index == 3:  # client.Initialize, shared mode and a three-second engine buffer
                assert arguments[1] == 0 and arguments[3] == 30_000_000
                assert arguments[2] == (0 if handle == 20 else 0x0002_0000)
            else:
                assert index in (10, 11), (handle, index)
        elif handle in (30, 31):
            self.capture(handle, index, arguments)
        else:
            raise AssertionError((handle, index))
        return 0

    def capture(self, handle: int, index: int, arguments: tuple[object, ...]) -> None:
        rate = self.format.nSamplesPerSec
        if index == 5:
            if missing := self.dropouts.pop((handle, self.delivered[handle]), 0):
                self.delivered[handle] += missing
                self.discontinuous.add(handle)
            available = round((self.now - self.origin) * rate) - self.delivered[handle]
            set_uint(arguments[1], self.packet_frames if available >= self.packet_frames else 0)
        elif index == 3:
            value = 1000 if handle == 30 else 2000
            samples = self.packet_frames * self.format.nChannels
            pcm = array("f", [value / 32768] * samples) if self.format.wFormatTag == 3 else array("h", [value] * samples)
            self.buffer = ctypes.create_string_buffer(pcm.tobytes())
            set_pointer(arguments[1], ctypes.addressof(self.buffer))
            set_uint(arguments[2], self.packet_frames)
            set_uint(arguments[3], 1 if not self.delivered[handle] or handle in self.discontinuous else self.flags)
            packet = self.delivered[handle] // self.packet_frames
            position = self.microphone_positions[packet] if handle == 30 and packet < len(self.microphone_positions) else self.delivered[handle]
            set_u64(arguments[4], position)
            set_u64(arguments[5], round((self.origin + self.delivered[handle] / rate) * 10_000_000))
        elif index == 4:
            self.delivered[handle] += self.packet_frames
            self.discontinuous.discard(handle)
        else:
            raise AssertionError((handle, index))


def test_continuous_loopback_and_microphone_share_a_clock_and_flush_on_stop() -> None:
    stop, ready = threading.Event(), threading.Event()
    blocks: list[bytes] = []
    api = Wasapi()
    recording.MeetingAudio(api).record(stop, blocks.append, ready.set, no_gap)
    assert ready.is_set()
    assert b"".join(blocks) == array("h", [3000] * round(2.54 * RATE)).tobytes()
    assert max(map(len, blocks)) < RATE * 2  # small callbacks even at final Stop
    for handle in (20, 21):
        assert api.calls.count((handle, 10)) == 1  # one Start, never at chunk boundaries
        assert api.calls.count((handle, 11)) == 1
    for handle in (1, 10, 11, 20, 21, 30, 31):
        assert api.calls.count((handle, 2)) == 1


def test_microphone_only_never_opens_the_playback_device() -> None:
    stop = threading.Event()
    blocks: list[bytes] = []
    api = Wasapi()
    recording.MeetingAudio(api, computer_audio=False).record(stop, blocks.append, lambda: None, no_gap)
    assert b"".join(blocks) == array("h", [1000] * round(2.54 * RATE)).tobytes()
    assert not any(handle in (11, 21, 31) for handle, _ in api.calls)


def test_microphone_discontinuities_do_not_end_a_meeting() -> None:
    stop = threading.Event()
    blocks: list[bytes] = []
    api = Wasapi()
    api.flags = 1
    recording.MeetingAudio(api, computer_audio=False).record(stop, blocks.append, lambda: None, no_gap)
    assert api.ticks == api.stop_at, "A microphone discontinuity ended capture before Stop."
    assert b"".join(blocks) == array("h", [1000] * round(2.54 * RATE)).tobytes()
    assert api.calls.count((20, 10)) == 1


def test_a_microphone_dropout_preserves_timing_and_other_speakers_until_stop() -> None:
    for computer_audio in (False, True):
        stop = threading.Event()
        blocks: list[bytes] = []
        api = Wasapi()
        api.dropouts = {(30, 48_000): 9_600}
        gaps: list[Problem] = []
        recording.MeetingAudio(api, computer_audio=computer_audio).record(stop, blocks.append, lambda: None, gaps.append)
        assert api.ticks == api.stop_at
        audio = array("h", b"".join(blocks))
        normal, gap = (3000, 2000) if computer_audio else (1000, 0)
        assert audio == array("h", [normal] * RATE + [gap] * (RATE // 5) + [normal] * round(1.34 * RATE))
        assert api.calls.count((20, 10)) == api.calls.count((20, 11)) == 1
        # Defect: audio the microphone lost before the drain is missing without a note.
        assert gaps == [Dropout(RATE, RATE // 5)]


def test_a_stalled_drain_keeps_every_buffered_packet_without_reporting_a_gap() -> None:
    # Defect: a capture loop that resumes after a multi-second stall (a busy
    # GIL, a slow journal) finds packets beyond its mixing ring and ends the
    # recording, though the engine buffered all of them.
    api = Wasapi()
    api.format = audio.WAVEFORMATEX(1, 1, RATE, RATE * 2, 2, 16, 0)
    api.packet_frames = 160
    api.stalls = {40: 5.0}
    blocks: list[bytes] = []
    problems: list[Problem] = []
    recording.MeetingAudio(api).record(threading.Event(), blocks.append, lambda: None, problems.append)
    assert api.ticks == api.stop_at
    assert b"".join(blocks) == array("h", [3000] * round(7.54 * RATE)).tobytes()
    # Defect: the stall that put the recording at risk leaves no measurement.
    match problems:
        case [Stall(seconds=seconds)]:
            assert 5 < seconds < 5.2, seconds
        case _:
            raise AssertionError(problems)


def test_forward_device_positions_need_not_advance_by_stream_packet_frames() -> None:
    # Defect: the real 48 kHz shared-mode stream supplies 480-frame packets
    # while its device counter advances 441. Comparing with the preceding
    # packet's calculated end misreports every second packet as a restart.
    api = Wasapi()
    api.microphone_positions = tuple(index * 441 for index in range(300))
    blocks: list[bytes] = []
    recording.MeetingAudio(api, computer_audio=False).record(threading.Event(), blocks.append, lambda: None, no_gap)
    result = b"".join(blocks)
    assert len(result) == round(2.54 * RATE) * 2
    assert result[1000:1200] == array("h", [1000] * 100).tobytes()


def test_a_backward_device_position_still_stops_recording() -> None:
    # Defect: relaxing the mixed-unit comparison hides a genuine clock reset.
    api = Wasapi()
    api.microphone_positions = (1000, 500)
    with unittest.TestCase().assertRaisesRegex(OSError, "restarted its audio clock"):
        recording.MeetingAudio(api).record(threading.Event(), lambda pcm: None, lambda: None, no_gap)


def test_cancelling_during_device_setup_never_starts_capture() -> None:
    stop = threading.Event()
    stop.set()
    api = Wasapi()
    recording.MeetingAudio(api).record(stop, lambda pcm: None, lambda: None, no_gap)
    assert not any(index == 10 for _, index in api.calls)
    assert (20, 2) in api.calls and (21, 2) in api.calls


def test_a_failed_second_device_start_releases_both_devices_and_stops_the_first() -> None:
    api = Wasapi()
    api.fail = (21, 10)
    with unittest.TestCase().assertRaises(OSError):
        recording.MeetingAudio(api).record(threading.Event(), lambda pcm: None, lambda: None, no_gap)
    assert (20, 11) in api.calls
    for handle in (1, 10, 11, 20, 21, 30, 31):
        assert api.calls.count((handle, 2)) == 1


def test_packet_clock_errors_return_the_driver_buffer_before_releasing_devices() -> None:
    stop = threading.Event()
    api = Wasapi()
    api.flags = 4
    with unittest.TestCase().assertRaisesRegex(OSError, "audio clock"):
        recording.MeetingAudio(api).record(stop, lambda pcm: None, lambda: None, no_gap)
    assert api.calls.count((30, 4)) == 2
    assert api.calls.index((30, 4)) < api.calls.index((30, 2))
    assert (20, 11) in api.calls and (21, 11) in api.calls


def test_digital_silence_is_kept() -> None:
    stop = threading.Event()
    blocks: list[bytes] = []
    api = Wasapi()
    api.flags = 2
    recording.MeetingAudio(api, computer_audio=False).record(stop, blocks.append, lambda: None, no_gap)
    result = b"".join(blocks)
    assert result[:320] == array("h", [1000] * 160).tobytes()
    assert not any(result[320:])
