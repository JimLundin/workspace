"""Voice capture through a concrete Windows input-device fixture."""

import ctypes
import sys
import threading
import unittest
from ctypes import wintypes
from enum import Enum
from typing import Literal, cast

if sys.platform != "win32":
    raise unittest.SkipTest("Windows audio bindings")

from winapi import audio
from winapi.system import EventHandle

RATE = 16_000
SPEECH = b"\x01\x00" * RATE + b"\x02\x00" * RATE + b"\x03\x00" * RATE


class Failure(Enum):
    NONE = "none"
    OPEN = "open"
    PREPARE = "prepare"
    ADD = "add"
    START = "start"
    RESET = "reset"
    UNPREPARE = "unprepare"
    POSITION = "position"


class Completion(Enum):
    RETURNED = "returned"
    DELAYED = "delayed"
    MISSING = "missing"


class InputDevice:
    """Owns simulated driver state and the capture buffer supplied by Microphone.

    Mutable driver observations model a device returning its buffer over time;
    no application objects or module bindings are replaced.
    """

    __slots__ = ("completion", "failure", "header", "now", "opened", "position_bytes", "positions", "release",
                 "reset_entered", "speech", "spoken_at", "started_at", "waits")

    def __init__(self) -> None:
        self.now = 0.0
        self.spoken_at = 0.0
        self.started_at: float | None = None
        self.speech = SPEECH
        self.header: audio.WAVEHDR | None = None
        self.opened = False
        self.failure = Failure.NONE
        self.completion = Completion.RETURNED
        self.waits = self.positions = 0
        self.position_bytes = 0
        self.reset_entered: threading.Event | None = None
        self.release: threading.Event | None = None

    def microphone(self) -> audio.Microphone:
        return audio.Microphone(RATE, 300, EventHandle(1), driver=self)

    def state(self) -> Literal["closed", "ready", "recording"]:
        if self.started_at is not None:
            return "recording"
        return "ready" if self.opened else "closed"

    def open(self, format: audio.WAVEFORMATEX, event: EventHandle) -> tuple[int, wintypes.HANDLE]:
        assert format.nSamplesPerSec == RATE and format.nChannels == 1 and format.wBitsPerSample == 16
        assert event == EventHandle(1)
        self.now += 1.0
        if self.failure is Failure.OPEN:
            return 5, wintypes.HANDLE()
        self.opened = True
        return 0, wintypes.HANDLE(1)

    def prepare(self, handle: wintypes.HANDLE, header: audio.WAVEHDR) -> int:
        return 5 if self.failure is Failure.PREPARE else 0

    def add(self, handle: wintypes.HANDLE, header: audio.WAVEHDR) -> int:
        if self.failure is Failure.ADD:
            return 5
        self.header = header
        return 0

    def start(self, handle: wintypes.HANDLE) -> int:
        if self.failure is Failure.START:
            return 5
        self.started_at = self.now
        return 0

    def reset(self, handle: wintypes.HANDLE) -> int:
        if self.reset_entered is not None:
            self.reset_entered.set()
        if self.release is not None:
            assert self.release.wait(2)
        if self.failure is Failure.RESET:
            return 5
        if self.header is not None and self.started_at is not None:
            beginning = round((self.started_at - self.spoken_at) * RATE) * 2
            end = round((self.now - self.spoken_at) * RATE) * 2
            recorded = self.speech[beginning:end]
            ctypes.memmove(cast("int", self.header.lpData), recorded, len(recorded))
            self.header.dwBytesRecorded = len(recorded)
        if self.header is not None:
            self.header.dwFlags = 1 if self.completion is Completion.RETURNED else 0
            if self.completion is not Completion.RETURNED:
                self.header.dwBytesRecorded = len(self.speech) // 2
        self.started_at = None
        return 0

    def unprepare(self, handle: wintypes.HANDLE, header: audio.WAVEHDR) -> int:
        return 5 if self.failure is Failure.UNPREPARE else 0

    def close(self, handle: wintypes.HANDLE) -> int:
        self.opened = False
        return 0

    def position(self, handle: wintypes.HANDLE, result: audio.MMTIME) -> int:
        self.positions += 1
        result.kind, result.value = 4, self.position_bytes
        return 5 if self.failure is Failure.POSITION else 0

    def wait(self, event: EventHandle, timeout_ms: int) -> bool:
        assert event == EventHandle(1) and 0 < timeout_ms <= 1000
        self.waits += 1
        if self.completion is Completion.MISSING:
            return False
        if self.waits == 2:
            assert self.header is not None
            self.header.dwBytesRecorded = len(self.speech)
            self.header.dwFlags = 1
        return True

    def say(self, mic: audio.Microphone) -> bytes:
        self.spoken_at = self.now  # speech starts with the key press
        assert mic.start() == 0
        self.now = self.spoken_at + len(self.speech) / (RATE * 2)
        return mic.stop()


def test_captures_the_first_words_spoken_immediately_on_press() -> None:
    device = InputDevice()
    mic = device.microphone()
    try:
        recorded = device.say(mic)
        assert recorded == SPEECH, f"Lost {(len(SPEECH) - len(recorded)) / (RATE * 2):.1f}s from the beginning"
    finally:
        mic.close()


def test_captures_the_first_words_again_after_an_idle_pause() -> None:
    device = InputDevice()
    mic = device.microphone()
    try:
        device.say(mic)
        device.now += 60
        device.speech = SPEECH[::-1]
        assert device.say(mic) == device.speech
    finally:
        mic.close()


def test_microphone_only_records_while_held_and_releases_the_device_on_close() -> None:
    device = InputDevice()
    mic = device.microphone()
    assert device.state() == "ready"
    assert mic.start() == 0
    assert device.state() == "recording"
    mic.stop()
    assert device.state() == "ready"
    assert mic.stop() == b""
    mic.close()
    assert device.state() == "closed"
    mic.close()


def test_closing_while_held_stops_recording_and_releases_the_device() -> None:
    device = InputDevice()
    mic = device.microphone()
    assert mic.start() == 0
    mic.close()
    assert device.state() == "closed"
    assert mic.stop() == b""


def test_failed_startup_open_is_reported_on_press_and_can_be_retried() -> None:
    device = InputDevice()
    device.failure = Failure.OPEN
    mic = device.microphone()
    assert mic.start() == 5
    assert device.state() == "closed"
    assert mic.stop() == b""
    mic.close()
    device.failure = Failure.NONE
    assert mic.start() == 0
    assert device.state() == "recording"
    mic.close()


def test_a_failed_recording_releases_the_device_and_can_be_retried() -> None:
    for failure in (Failure.PREPARE, Failure.ADD, Failure.START):
        device = InputDevice()
        mic = device.microphone()
        device.failure = failure
        assert mic.start() == 5
        assert device.state() == "closed"
        assert mic.stop() == b""
        device.failure = Failure.NONE
        assert mic.start() == 0
        mic.close()


def test_stop_waits_for_the_final_audio_buffer_after_a_stale_open_event() -> None:
    """Detect reading the last byte count before the driver returns its buffer."""
    device = InputDevice()
    device.completion = Completion.DELAYED
    mic = device.microphone()
    try:
        assert device.say(mic) == SPEECH, "The last half of the voice prompt was cut off"
        assert device.waits == 2
    finally:
        mic.close()


def test_a_stop_error_is_reported_and_the_next_capture_can_retry() -> None:
    for failure in (Failure.RESET, Failure.UNPREPARE):
        device = InputDevice()
        mic = device.microphone()
        device.failure = failure
        with unittest.TestCase().assertRaises(OSError):
            device.say(mic)
        device.failure = Failure.NONE
        assert device.say(mic) == SPEECH
        mic.close()


def test_an_unreturned_buffer_times_out_without_giving_back_partial_audio() -> None:
    device = InputDevice()
    device.completion = Completion.MISSING
    mic = device.microphone()
    with unittest.TestCase().assertRaisesRegex(OSError, "complete recording"):
        device.say(mic)
    device.completion = Completion.RETURNED
    assert device.say(mic) == SPEECH
    mic.close()


def test_live_meter_reads_recorded_pcm_without_trusting_the_unfinished_header() -> None:
    device = InputDevice()
    mic = device.microphone()
    assert mic.level() is None
    device.spoken_at = device.now
    assert mic.start() == 0
    assert device.header is not None
    pcm = b"\x00\x40" * 640  # constant half-scale signal, exactly 40 ms
    ctypes.memmove(cast("int", device.header.lpData), pcm, len(pcm))
    assert cast(int, device.header.dwBytesRecorded) == 0
    device.position_bytes = len(pcm)
    assert mic.level() == .5
    assert mic.level() == 0  # No new data: don't invent continued activity.
    device.failure = Failure.POSITION
    assert mic.level() is None
    device.failure = Failure.NONE
    device.now += 3
    assert mic.stop() == SPEECH  # Metering has not changed the final recording.
    assert mic.level() is None
    mic.close()


def test_meter_never_waits_for_capture_shutdown_or_buffer_release() -> None:
    device = InputDevice()
    mic = device.microphone()
    assert mic.start() == 0
    held, release = threading.Event(), threading.Event()
    device.reset_entered, device.release = held, release
    worker = threading.Thread(target=mic.stop)
    worker.start()
    try:
        assert held.wait(1)
        assert mic.level() is None
        assert device.positions == 0
    finally:
        release.set()
        worker.join(2)
        mic.close()
