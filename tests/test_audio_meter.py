"""Capture-bound observations cannot block the UI or outlive their own capture."""

import threading
import time

from assistant.audio_meter import AudioMeter


def test_stopped_capture_cannot_publish_into_the_next_waveform() -> None:
    first, release_first, second, release_second = (threading.Event() for _ in range(4))
    calls = 0

    def read() -> float:
        nonlocal calls
        calls += 1
        if calls == 1:
            first.set()
            release_first.wait(1)
            return .9
        second.set()
        release_second.wait(1)
        return .2

    meter = AudioMeter(read)
    try:
        assert meter.level() is None and not first.is_set()
        meter.listen(enabled=True)
        assert first.wait(1)
        meter.listen(enabled=False)
        assert meter.level() is None
        meter.listen(enabled=True)
        release_first.set()
        assert second.wait(1)
        assert meter.level() is None, "An old capture's sample leaked into the new waveform."
        release_second.set()
        deadline = time.monotonic() + 1
        while meter.level() is None and time.monotonic() < deadline:
            time.sleep(.005)
        assert meter.level() == .2
        meter.listen(enabled=False)
        assert meter.level() is None
    finally:
        release_first.set()
        release_second.set()
        meter.close()


def test_blocked_observer_does_not_keep_old_audio_alive_or_read_after_close() -> None:
    first, blocked, release = (threading.Event() for _ in range(3))
    now = [100.0]
    calls = 0

    def read() -> float:
        nonlocal calls
        calls += 1
        if calls == 1:
            first.set()
        else:
            blocked.set()
            release.wait(1)
        return .5

    meter = AudioMeter(read, clock=lambda: now[0])
    try:
        meter.listen(enabled=True)
        assert first.wait(1) and blocked.wait(1)
        assert meter.level() == .5
        now[0] += .3
        assert meter.level() is None, "A stalled driver must not show stale speech as current."
        meter.close()
        release.set()
        meter.worker.join(timeout=1)
        assert not meter.worker.is_alive() and calls == 2
        assert meter.level() is None
    finally:
        release.set()
        meter.close()
