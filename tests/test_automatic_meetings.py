"""Owned recording decisions through manual commands and real saved opt-in."""

import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

from assistant.automatic_meetings import AutomaticAttention, AutomaticMeetings
from assistant.meeting_detection import (
    PREFERENCE,
    AutomaticPreference,
    AutomaticStatus,
    Call,
    Calls,
    Observation,
    ObservationFailure,
)
from assistant.recording_state import RecordingState
from assistant.state_store import SavedState
from automation.capture import AudioSource

CALL = Calls((Call("private-call", "Workspace private meeting"),))


def test_monitor_warns_once_for_a_sustained_outage_and_ignores_flapping() -> None:
    # Defect: each brief Edge/page failure produces another desktop warning,
    # even though monitoring recovers on the next poll or the outage is unchanged.
    now = 0.0
    statuses: list[AutomaticStatus] = []
    warnings: list[float] = []
    attention = AutomaticAttention(statuses.append, lambda: warnings.append(now), lambda: now)
    attention.changed(AutomaticStatus.UNAVAILABLE)
    now = 5
    attention.changed(AutomaticStatus.READY)
    now = 10
    attention.changed(AutomaticStatus.UNAVAILABLE)
    now = 39
    attention.changed(AutomaticStatus.UNAVAILABLE)
    assert not warnings
    now = 40
    attention.changed(AutomaticStatus.UNAVAILABLE)
    assert warnings == [40]
    for at, status in ((45, AutomaticStatus.READY), (50, AutomaticStatus.UNAVAILABLE), (55, AutomaticStatus.READY), (84, AutomaticStatus.READY)):
        now = at
        attention.changed(status)
    assert warnings == [40] and statuses[-1] is AutomaticStatus.READY
    now = 84.5
    attention.changed(AutomaticStatus.UNAVAILABLE)
    now = 114.5
    attention.changed(AutomaticStatus.UNAVAILABLE)
    assert warnings == [40], "A 29-second recovery must not rearm outage warnings."
    now = 120
    attention.changed(AutomaticStatus.READY)
    now = 150
    attention.changed(AutomaticStatus.READY)
    now = 155
    attention.changed(AutomaticStatus.UNAVAILABLE)
    now = 185
    attention.changed(AutomaticStatus.UNAVAILABLE)
    assert warnings == [40, 185]


class LocalRecording:
    """A concrete recorder publishes immutable observations and effect receipts.

    This fixture owns its replacements, as a recorder owns its device state;
    no imported function or instance method is replaced.
    """

    def __init__(self) -> None:
        self.state = RecordingState()
        self.starts: tuple[tuple[AudioSource, str], ...] = ()
        self.stops = 0
        self.failure: str | None = None

    def snapshot(self) -> RecordingState:
        return self.state

    def start(self, source: AudioSource = "both", title: str = "Meeting") -> None:
        if self.failure is not None:
            raise OSError(self.failure)
        if self.state.capturing:
            raise OSError("Already capturing")
        receipt: tuple[AudioSource, str] = (source, title)
        self.starts += (receipt,)
        self.state = RecordingState(phase="recording", identity=str(len(self.starts)), title=title, source=source)

    def stop(self) -> None:
        self.stops += 1
        self.state = replace(self.state, phase="saved")

    def history(self) -> tuple[tuple[AudioSource, str], ...]:
        return self.starts


class LocalCalls:
    """Own a typed observation source, with gates for an in-flight native read."""

    def __init__(self) -> None:
        self.current: Observation = CALL
        self.entered, self.release = threading.Event(), threading.Event()
        self.release.set()
        self.reads = 0
        self.closed = False

    def observe(self, cancel: threading.Event) -> Observation:
        self.reads += 1
        current = self.current
        self.entered.set()
        assert self.release.wait(3), "The test did not release its observation."
        return current

    def close(self) -> None:
        self.closed = True


class PlainStorage:
    """Local opt-in storage without the Windows encryption boundary."""

    def protect(self, data: bytes) -> bytes:
        return data

    def unprotect(self, data: bytes) -> bytes:
        return data


def monitor(folder: Path) -> tuple[AutomaticMeetings, LocalRecording, LocalCalls]:
    recorder, observer = LocalRecording(), LocalCalls()
    saved = SavedState(folder / "automatic.bin", PREFERENCE, cipher=PlainStorage())
    owner = AutomaticMeetings(recorder, observer, saved, publish=lambda _: None)
    return owner, recorder, observer


def test_opt_in_is_saved_and_disabled_monitor_does_not_read_browser(tmp_path: Path) -> None:
    # Defect: opting in is lost on restart, or off still touches the browser.
    owner, recorder, observer = monitor(tmp_path)
    try:
        owner.poll(0)
        assert observer.reads == 0 and recorder.history() == ()
        owner.toggle()
        assert owner.store.read() == AutomaticPreference(enabled=True)
        restarted = AutomaticMeetings(recorder, observer, owner.store, publish=lambda _: None)
        restarted.poll(1)
        assert recorder.history() == (("both", "Workspace private meeting"),)
        restarted.close()
    finally:
        owner.close()


def test_call_starts_once_and_departure_is_debounced(tmp_path: Path) -> None:
    # Defect: every poll starts another capture, or a transient redraw stops it.
    owner, recorder, observer = monitor(tmp_path)
    try:
        owner.toggle()
        owner.poll(0)
        owner.poll(5)
        observer.current = Calls(())
        owner.poll(10)
        assert recorder.stops == 0
        observer.current = CALL
        owner.poll(15)
        observer.current = Calls(())
        owner.poll(20)
        owner.poll(29)
        assert recorder.stops == 0
        owner.poll(30)
        assert recorder.stops == 1 and len(recorder.starts) == 1
        observer.current = CALL
        owner.poll(35)
        assert len(recorder.starts) == 2
    finally:
        owner.close()


def test_manual_stop_and_capture_failure_suppress_restart_in_same_call(tmp_path: Path) -> None:
    # Defect: automatic monitoring overrides Stop, or repeatedly retries a broken device.
    owner, recorder, observer = monitor(tmp_path)
    try:
        owner.toggle()
        owner.poll(0)
        owner.stop_recording()
        owner.poll(5)
        owner.poll(10)
        assert len(recorder.starts) == 1 and recorder.stops == 1
        observer.current = Calls(())
        owner.poll(15)
        owner.poll(25)
        recorder.failure = "Microphone unavailable"
        observer.current = CALL
        owner.poll(30)
        recorder.failure = None
        owner.poll(35)
        assert len(recorder.starts) == 1
    finally:
        owner.close()


def test_manual_capture_is_never_stopped_on_departure_or_disable(tmp_path: Path) -> None:
    # Defect: leaving Teams or disabling auto-record stops a separate manual capture.
    owner, recorder, observer = monitor(tmp_path)
    try:
        owner.start_recording("microphone", "Personal notes")
        owner.toggle()
        owner.poll(0)
        observer.current = Calls(())
        owner.poll(5)
        owner.poll(15)
        owner.toggle()
        assert recorder.stops == 0 and recorder.state.capturing
    finally:
        owner.close()


def test_connection_failure_stops_only_owned_audio_after_bounded_grace(tmp_path: Path) -> None:
    # Defect: an unavailable read is treated as immediate departure, leaves
    # unattended capture running indefinitely, or restarts it on recovery.
    owner, recorder, observer = monitor(tmp_path)
    try:
        owner.toggle()
        owner.poll(0)
        observer.current = ObservationFailure.UNAVAILABLE
        owner.poll(29)
        assert recorder.stops == 0
        owner.poll(30)
        owner.poll(40)
        assert recorder.stops == 1
        observer.current = CALL
        owner.poll(45)
        assert len(recorder.starts) == 1
    finally:
        owner.close()


def test_manual_stop_invalidates_in_flight_join_observation(tmp_path: Path) -> None:
    # Defect: a browser read admitted before Stop starts capture after Stop returns.
    owner, recorder, observer = monitor(tmp_path)
    try:
        owner.toggle()
        observer.release.clear()
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(owner.poll, 0)
            assert observer.entered.wait(2)
            owner.stop_recording()
            observer.release.set()
            pending.result(3)
        owner.poll(5)
        assert recorder.starts == ()
        observer.current = Calls(())
        owner.poll(10)
        owner.poll(20)
        observer.current = CALL
        owner.poll(25)
        assert len(recorder.starts) == 1
    finally:
        observer.release.set()
        owner.close()


def test_monitor_reports_connection_and_start_failures(tmp_path: Path) -> None:
    # Defect: the menu claims monitoring is ready after a failed browser/device effect.
    owner, recorder, observer = monitor(tmp_path)
    status = StatusPublication()
    reporting = AutomaticMeetings(recorder, observer, owner.store, publish=status)
    try:
        reporting.toggle()
        observer.current = ObservationFailure.UNAVAILABLE
        reporting.poll(0)
        assert status.latest() is AutomaticStatus.UNAVAILABLE
        observer.current = Calls(())
        reporting.poll(5)
        assert status.latest() is AutomaticStatus.READY
        recorder.failure = "Capture unavailable"
        observer.current = CALL
        reporting.poll(10)
        assert status.latest() is AutomaticStatus.UNAVAILABLE
        recorder.failure = None
        reporting.poll(15)
        assert status.latest() is AutomaticStatus.UNAVAILABLE and recorder.history() == ()
    finally:
        reporting.close()
        owner.close()


class StatusPublication:
    """The concrete UI port owns its latest immutable publication."""

    def __init__(self) -> None:
        self.current: AutomaticStatus = AutomaticStatus.OFF

    def __call__(self, status: AutomaticStatus) -> None:
        self.current = status

    def latest(self) -> AutomaticStatus:
        return self.current
