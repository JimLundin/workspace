"""Own saved opt-in, low-frequency Teams observation and automatic capture lifetime."""

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Protocol

from assistant.lifecycle import joined
from assistant.state_store import SavedState
from cell import Cell
from contracts.capture import AudioSource
from contracts.meeting_detection import (
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
from contracts.recording_state import RecordingState


class CallObserver(Protocol):
    def observe(self, cancel: threading.Event) -> Observation: ...
    def close(self) -> None: ...


class Recorder(Protocol):
    def snapshot(self) -> RecordingState: ...
    def start(self, source: AudioSource = "both", title: str = "Meeting") -> None: ...
    def stop(self) -> None: ...


@dataclass(frozen=True, slots=True)
class _Attended:
    notice: NoticeState = Available.MONITOR
    status: AutomaticStatus | None = None
    """The last status published."""


@dataclass(frozen=True, slots=True)
class AutomaticAttention:
    """Own status publication, the monotonic clock and desktop warning effects.

    Only this callback owner replaces its immutable attention/status observations;
    repeated poll samples assess recovery without repainting the unchanged status.
    """

    publish: Callable[[AutomaticStatus], None]
    warn: Callable[[], None]
    clock: Callable[[], float] = time.monotonic
    _attended: Cell[_Attended] = field(default_factory=lambda: Cell(_Attended()), init=False, repr=False)

    def changed(self, status: AutomaticStatus) -> None:
        attended = self._attended.get()
        decision = monitor_attention(attended.notice, MonitorSample(status, self.clock()))
        self._attended.set(_Attended(decision.state, status))
        if status is not attended.status:
            self.publish(status)
        if decision.warning is Warning.SHOW:
            self.warn()


@dataclass(frozen=True, slots=True)
class _Monitoring:
    preference: AutomaticPreference
    status: AutomaticStatus
    watch: Watch = Idle.WAITING
    revision: int = 0
    """Manual commands invalidate an in-flight browser observation."""


@dataclass(frozen=True, slots=True)
class AutomaticMeetings:
    """The lock serializes manual commands with monitor decisions and their effects.

    Only this owner replaces its immutable watch/preference/status observations;
    native thread/event/lock lifetime requires local mutation. The browser runs
    outside the lock. Five-second polling avoids animation/key-event workloads.
    """

    # Recording, browser observation, saved opt-in and UI publication have
    # independent ownership and lifecycle; these are composition dependencies.
    recorder: Recorder
    observer: CallObserver
    store: SavedState[AutomaticPreference]
    _state: Cell[_Monitoring]
    """Replaced whole under the lock."""
    publish: Callable[[AutomaticStatus], None] = field(kw_only=True)
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False, repr=False)
    _quit: threading.Event = field(default_factory=threading.Event, init=False, repr=False)
    _wake: threading.Event = field(default_factory=threading.Event, init=False, repr=False)
    _started: threading.Event = field(default_factory=threading.Event, init=False, repr=False)
    _finished: threading.Event = field(default_factory=threading.Event, init=False, repr=False)
    """Set when the worker thread's run returns; a started thread isn't kept."""

    @classmethod
    def load(
        cls,
        recorder: Recorder,
        observer: CallObserver,
        store: SavedState[AutomaticPreference],
        *,
        publish: Callable[[AutomaticStatus], None],
    ) -> AutomaticMeetings:
        """The monitor with the saved opt-in."""
        preference = store.read()
        status = AutomaticStatus.CHECKING if preference.enabled else AutomaticStatus.OFF
        return cls(recorder, observer, store, Cell(_Monitoring(preference, status)), publish=publish)

    def start(self) -> None:
        with self._lock:
            self.publish(self._state.get().status)
            if not self._started.is_set():
                self._started.set()
                threading.Thread(target=self._finishing, args=(self._run,), name="Teams meeting monitor", daemon=True).start()

    def _finishing(self, run: Callable[[], None]) -> None:
        try:
            run()
        finally:
            self._finished.set()

    def toggle(self) -> None:
        with self._lock:
            preference = AutomaticPreference(enabled=not self._state.get().preference.enabled)
            self.store.write(preference)
            self._state.set(replace(self._state.get(), preference=preference))
            self._state.set(replace(self._state.get(), revision=self._state.get().revision + 1))
            if not preference.enabled:
                match self._state.get().watch:
                    case Watching(ownership=Ownership.AUTOMATIC):
                        self.recorder.stop()
                    case _:
                        pass
                self._state.set(replace(self._state.get(), watch=Idle.WAITING))
            self._state.set(replace(self._state.get(), status=AutomaticStatus.CHECKING if preference.enabled else AutomaticStatus.OFF))
            self.publish(self._state.get().status)
        self._wake.set()

    def start_recording(self, source: AudioSource, title: str = "Meeting") -> None:
        with self._lock:
            self.recorder.start(source, title)
            new_watch = suppressed(self._state.get().watch)
            self._state.set(replace(self._state.get(), watch=new_watch))
            self._state.set(replace(self._state.get(), revision=self._state.get().revision + 1))

    def stop_recording(self) -> None:
        with self._lock:
            new_watch = suppressed(self._state.get().watch)
            self._state.set(replace(self._state.get(), watch=new_watch))
            self._state.set(replace(self._state.get(), revision=self._state.get().revision + 1))
            self.recorder.stop()

    def poll(self, at: float) -> None:
        """Observe outside the command lock, rechecking opt-in before any effect."""
        with self._lock:
            if not self._state.get().preference.enabled or self._quit.is_set():
                return
            preference = self._state.get().preference
            revision = self._state.get().revision
        observation = self.observer.observe(self._quit)
        with self._lock:
            if self._quit.is_set() or self._state.get().preference is not preference or self._state.get().revision != revision:
                return
            match observation:
                case Calls():
                    status = AutomaticStatus.READY
                case ObservationFailure.UNAVAILABLE:
                    status = AutomaticStatus.UNAVAILABLE
            decision = decide(self._state.get().watch, Sample(observation, self.recorder.snapshot(), at))
            self._state.set(replace(self._state.get(), watch=decision.watch))
            try:
                match decision.effect:
                    case Start(call):
                        self.recorder.start("both", call.title)
                    case Effect.STOP:
                        self.recorder.stop()
                    case Effect.NONE:
                        pass
            except OSError, ValueError:
                match self._state.get().watch:
                    case Watching() as watching:
                        self._state.set(replace(self._state.get(), watch=replace(watching, ownership=Ownership.FAILED)))
                    case Idle():
                        pass
                status = AutomaticStatus.UNAVAILABLE
            match self._state.get().watch:
                case Watching(ownership=Ownership.FAILED):
                    status = AutomaticStatus.UNAVAILABLE
                case _:
                    pass
            self._state.set(replace(self._state.get(), status=status))
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
        joined(self._started, self._finished, self.observer.close, "The Teams meeting monitor did not release its browser connection.")
