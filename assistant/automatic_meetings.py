"""Own saved opt-in, low-frequency Teams observation and automatic capture lifetime."""

import threading
import time
from collections.abc import Callable
from dataclasses import replace
from typing import Protocol

from assistant.meeting_detection import (
    AutomaticPreference,
    AutomaticStatus,
    Available,
    Calls,
    Effect,
    Idle,
    MonitorSample,
    NoticeState,
    Observation,
    ObservationFailure,
    Ownership,
    Sample,
    Start,
    Warning,
    Watch,
    Watching,
    decide,
    monitor_attention,
    suppressed,
)
from assistant.recording_state import RecordingState
from assistant.state_store import SavedState
from automation.capture import AudioSource


class CallObserver(Protocol):
    def observe(self, cancel: threading.Event) -> Observation: ...
    def close(self) -> None: ...


class Recorder(Protocol):
    def snapshot(self) -> RecordingState: ...
    def start(self, source: AudioSource = "both", title: str = "Meeting") -> None: ...
    def stop(self) -> None: ...


class AutomaticAttention:
    """Own status publication, the monotonic clock and desktop warning effects.

    Only this callback owner replaces its immutable attention/status observations;
    repeated poll samples assess recovery without repainting the unchanged status.
    """

    __slots__ = ("_state", "_status", "clock", "publish", "warn")

    def __init__(self, publish: Callable[[AutomaticStatus], None], warn: Callable[[], None], clock: Callable[[], float] = time.monotonic) -> None:
        self.publish, self.warn, self.clock = publish, warn, clock
        self._state: NoticeState = Available.MONITOR
        self._status: AutomaticStatus | None = None

    def changed(self, status: AutomaticStatus) -> None:
        decision = monitor_attention(self._state, MonitorSample(status, self.clock()))
        self._state = decision.state
        if status is not self._status:
            self._status = status
            self.publish(status)
        if decision.warning is Warning.SHOW:
            self.warn()


class AutomaticMeetings:
    """The lock serializes manual commands with monitor decisions and their effects.

    Only this owner replaces its immutable watch/preference/status observations;
    native thread/event/lock lifetime requires local mutation. The browser runs
    outside the lock. Five-second polling avoids animation/key-event workloads.
    """

    __slots__ = ("_lock", "_preference", "_quit", "_revision", "_status", "_thread", "_wake", "_watch", "observer", "publish", "recorder", "store")

    # Recording, browser observation, saved opt-in and UI publication have
    # independent ownership and lifecycle; these are composition dependencies.
    def __init__(
        self,
        recorder: Recorder,
        observer: CallObserver,
        store: SavedState[AutomaticPreference],
        *,
        publish: Callable[[AutomaticStatus], None],
    ) -> None:
        self.recorder, self.observer, self.store, self.publish = recorder, observer, store, publish
        self._lock = threading.RLock()
        self._quit, self._wake = threading.Event(), threading.Event()
        self._thread: threading.Thread | None = None
        self._watch: Watch = Idle.WAITING
        self._revision = 0  # Manual commands invalidate an in-flight browser observation.
        self._preference = store.read()
        self._status = AutomaticStatus.CHECKING if self._preference.enabled else AutomaticStatus.OFF

    def start(self) -> None:
        with self._lock:
            self.publish(self._status)
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, name="Teams meeting monitor", daemon=True)
                self._thread.start()

    def toggle(self) -> None:
        with self._lock:
            preference = AutomaticPreference(enabled=not self._preference.enabled)
            self.store.write(preference)
            self._preference = preference
            self._revision += 1
            if not preference.enabled:
                match self._watch:
                    case Watching(ownership=Ownership.AUTOMATIC):
                        self.recorder.stop()
                    case _:
                        pass
                self._watch = Idle.WAITING
            self._status = AutomaticStatus.CHECKING if preference.enabled else AutomaticStatus.OFF
            self.publish(self._status)
        self._wake.set()

    def start_recording(self, source: AudioSource, title: str = "Meeting") -> None:
        with self._lock:
            self.recorder.start(source, title)
            self._watch = suppressed(self._watch)
            self._revision += 1

    def stop_recording(self) -> None:
        with self._lock:
            self._watch = suppressed(self._watch)
            self._revision += 1
            self.recorder.stop()

    def poll(self, at: float) -> None:
        """Observe outside the command lock, rechecking opt-in before any effect."""
        with self._lock:
            if not self._preference.enabled or self._quit.is_set():
                return
            preference = self._preference
            revision = self._revision
        observation = self.observer.observe(self._quit)
        with self._lock:
            if self._quit.is_set() or self._preference is not preference or self._revision != revision:
                return
            match observation:
                case Calls():
                    status = AutomaticStatus.READY
                case ObservationFailure.UNAVAILABLE:
                    status = AutomaticStatus.UNAVAILABLE
            decision = decide(self._watch, Sample(observation, self.recorder.snapshot(), at))
            self._watch = decision.watch
            try:
                match decision.effect:
                    case Start(call):
                        self.recorder.start("both", call.title)
                    case Effect.STOP:
                        self.recorder.stop()
                    case Effect.NONE:
                        pass
            except OSError, ValueError:
                match self._watch:
                    case Watching():
                        self._watch = replace(self._watch, ownership=Ownership.FAILED)
                    case Idle():
                        pass
                status = AutomaticStatus.UNAVAILABLE
            match self._watch:
                case Watching(ownership=Ownership.FAILED):
                    status = AutomaticStatus.UNAVAILABLE
                case _:
                    pass
            self._status = status
            self.publish(status)

    def _run(self) -> None:
        try:
            while not self._quit.is_set():
                self.poll(time.monotonic())
                self._wake.wait(5)
                self._wake.clear()
        finally:
            self.observer.close()

    def close(self) -> None:
        self._quit.set()
        self._wake.set()
        thread = self._thread
        if thread is not None:
            thread.join(20)
            if thread.is_alive():
                raise OSError("The Teams meeting monitor did not release its browser connection.")
        else:
            self.observer.close()
