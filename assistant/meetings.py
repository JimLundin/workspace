"""Explicit long-running recording, independent of dictation, model work and the UI.

The real-time capture thread only hands audio to a bounded in-memory spool. A
journal thread writes it one second at a time and publishes progress every few
seconds. A separate worker transcribes 20-30 second chunks, retries outages, and
resumes pending text work after a restart. Restarting Workspace never resumes
microphone or computer-audio capture.
"""

import queue
import sqlite3
import threading
import time
import traceback
from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Final, Protocol

from assistant.llm import Failure, Settings, transcribe, wav
from assistant.meeting_store import MeetingArchive, MeetingStore
from cell import Cell
from contracts.capture import AudioSource
from contracts.recording_state import SOURCE_NAMES, Exhausted, Phase, Publication, RecordingState, RetryPolicy, capture_report, published
from diagnostics import DIRECTORY
from winapi.pcm import RATE, Problem


class Transcriber(Protocol):
    def __call__(self, audio: bytes, *, context: str) -> str | Failure: ...


class Capture(Protocol):
    def record(
        self, stop: threading.Event, consume: Callable[[bytes], None], ready: Callable[[], None], report: Callable[[Problem], None]
    ) -> None: ...


SPOOL_SECONDS: Final = 60
"""Audio the capture thread may hand over while the journal is slow (a busy disk or a long reader)."""
PUBLISH_SECONDS: Final = 2.0
"""At most one progress publication per interval while capturing; storage, not the UI, paces capture."""


class SpoolFullError(OSError):
    """The journal fell further behind capture than the spool holds; capture must end."""


@dataclass(frozen=True, slots=True)
class Handover:
    """What the journal thread takes from the spool in one wake."""

    pcm: bytes
    problems: tuple[Problem, ...] = ()
    flagged: bool = False
    closed: bool = False


@dataclass(frozen=True, slots=True)
class _Spooled:
    blocks: tuple[bytes, ...] = ()
    problems: tuple[Problem, ...] = ()
    size: int = 0
    """Bytes held in `blocks`."""
    flagged: bool = False
    closed: bool = False


@dataclass(frozen=True, slots=True)
class Spool:
    """A bounded handover from the real-time capture thread to the journal thread.

    `put` never waits for storage: it holds the lock only to append. A block that
    would exceed the bound is refused, which ends the recording.
    """

    limit: int = RATE * 2 * SPOOL_SECONDS
    _spooled: Cell[_Spooled] = field(default_factory=lambda: Cell(_Spooled()), init=False, repr=False)
    """Replaced whole under the condition."""
    _condition: threading.Condition = field(default_factory=threading.Condition, init=False, repr=False)

    def put(self, pcm: bytes) -> None:
        if len(pcm) % 2:
            raise ValueError("The capture device returned an invalid audio block.")
        with self._condition:
            spooled = self._spooled.get()
            if spooled.size + len(pcm) > self.limit:
                raise SpoolFullError(
                    f"Recording stopped: saving fell more than {self.limit // (RATE * 2)} s behind the audio devices. "
                    "The captured part has been saved."
                )
            self._spooled.set(replace(spooled, blocks=(*spooled.blocks, pcm), size=spooled.size + len(pcm)))
            self._condition.notify()

    def report(self, problem: Problem) -> None:
        with self._condition:
            self._spooled.update(lambda spooled: replace(spooled, problems=(*spooled.problems, problem)))
            self._condition.notify()

    def flag(self) -> None:
        """Ask the journal thread to publish the current state soon."""
        with self._condition:
            self._spooled.update(lambda spooled: replace(spooled, flagged=True))
            self._condition.notify()

    def close(self) -> None:
        with self._condition:
            self._spooled.update(lambda spooled: replace(spooled, closed=True))
            self._condition.notify()

    def take(self, timeout: float) -> Handover:
        with self._condition:

            def ready() -> bool:
                spooled = self._spooled.get()
                return bool(spooled.blocks or spooled.problems or spooled.flagged or spooled.closed)

            self._condition.wait_for(ready, timeout)
            spooled = self._spooled.get()
            self._spooled.set(_Spooled(closed=spooled.closed))
            return Handover(b"".join(spooled.blocks), spooled.problems, flagged=spooled.flagged, closed=spooled.closed)


@dataclass(frozen=True, slots=True)
class _Blocks:
    """Cut handed-over audio into the journal's one-second blocks."""

    store: MeetingStore

    def feed(self, pending: bytes, pcm: bytes) -> tuple[bytes, bool]:
        """Append every whole block of `pending + pcm`; the rest waits for more, and whether any was written."""
        audio = pending + pcm
        whole = len(audio) - len(audio) % (RATE * 2)
        for start in range(0, whole, RATE * 2):
            self.store.append(audio[start : start + RATE * 2])
        return audio[whole:], whole > 0


@dataclass(frozen=True, slots=True)
class _Journal:
    """The capture's storage owner: writes spooled audio and paces its publication."""

    store: MeetingStore
    spool: Spool
    changed: Callable[[], None]
    publish: Callable[[], None]
    log: Callable[[str], None]
    outcome: Future[str] = field(default_factory=Future[str], init=False, repr=False)
    """Why the journal stopped saving, or empty when it saved everything; set when `run` returns."""

    @property
    def problem(self) -> str:
        return self.outcome.result() if self.outcome.done() else ""

    def run(self, stop: threading.Event) -> None:
        problem = self._journal()
        self.outcome.set_result(problem)
        if problem:
            # Saving failed: end capture, and never store audio captured after the failure.
            stop.set()

    def _journal(self) -> str:
        blocks, pending = _Blocks(self.store), b""
        published, dirty = time.monotonic() - PUBLISH_SECONDS, False
        try:
            while True:
                due = published + PUBLISH_SECONDS - time.monotonic()
                taken = self.spool.take(max(0.0, due) if dirty else PUBLISH_SECONDS)
                pending, written = blocks.feed(pending, taken.pcm)
                if written:
                    self.changed()
                    dirty = True
                if taken.problems:
                    # Recovered timing problems are notes on the recording, never its end.
                    report = capture_report(taken.problems)
                    self.log(f"{report.text} Recording {self.store.folder.name} continues.")
                    if report.gaps:
                        self.store.record_gaps(report.gaps, report.gap_frames)
                        dirty = True
                now = time.monotonic()
                # A phase change publishes even when capture has already ended.
                if taken.flagged or (dirty and now - published >= PUBLISH_SECONDS and not taken.closed):
                    self.publish()
                    published, dirty = now, False
                if taken.closed:
                    self.store.append(pending)
                    self.changed()
                    return ""
        except (OSError, ValueError, sqlite3.Error) as error:
            return str(error)
        except Exception:
            self.log(traceback.format_exc())
            return "Recording stopped unexpectedly. The captured part is saved in the meetings folder."


def _unlogged(text: str) -> None:
    pass


@dataclass(frozen=True, slots=True)
class _Recording:
    state: RecordingState = field(default_factory=RecordingState)
    """What the view shows."""
    stop: threading.Event = field(default_factory=threading.Event)
    """The current capture's stop signal; each capture gets its own."""
    capture: threading.Thread | None = None
    worker: threading.Thread | None = None
    closing: bool = False
    scheduled: frozenset[Path] = frozenset()
    """Journals queued for transcription."""
    paused: frozendict[Path, str] = frozendict()
    """Journals whose transcription is paused, and why."""
    retry_pending: frozenset[Path] = frozenset()
    """Scheduled journals the user asked to retry."""


@dataclass(frozen=True, slots=True)
class Meetings:
    # Capture, transcription, storage and their independent publications
    # are effect dependencies; no callback owns another owner's progress.
    settings: Settings
    factory: Callable[[AudioSource], Capture]
    archive: MeetingArchive
    transcribe_audio: Transcriber
    retry_policy: RetryPolicy
    on_update: Callable[[RecordingState], None] | None
    log: Callable[[str], None]
    _recovery: tuple[Path, ...]
    """Journals found at startup, scheduled once the worker runs."""
    _state: Cell[_Recording] = field(default_factory=lambda: Cell(_Recording()), init=False, repr=False)
    """Replaced whole under the lock."""
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False, repr=False)
    _emitting: threading.RLock = field(default_factory=threading.RLock, init=False, repr=False)
    """Serializes publications in state order without holding `_lock`: the
    view takes its own locks, and capture or snapshot() must never wait for them."""
    _quit: threading.Event = field(default_factory=threading.Event, init=False, repr=False)
    _wake: threading.Event = field(default_factory=threading.Event, init=False, repr=False)
    _queue: queue.Queue[MeetingStore | None] = field(default_factory=queue.Queue[MeetingStore | None], init=False, repr=False)

    @classmethod
    def open(  # noqa: PLR0913 - injected collaborators and callbacks
        cls,
        settings: Settings,
        factory: Callable[[AudioSource], Capture],
        *,
        archive: MeetingArchive | None = None,
        on_update: Callable[[RecordingState], None] | None = None,
        transcribe_audio: Transcriber | None = None,
        retry_policy: RetryPolicy | None = None,
        log: Callable[[str], None] | None = None,
    ) -> Meetings:
        """The recorder over `archive`, with its unfinished journals found for recovery."""
        archive = archive if archive is not None else MeetingArchive(DIRECTORY / "meetings")

        def configured_transcriber(audio: bytes, *, context: str) -> str | Failure:
            return transcribe(settings, audio, context=context)

        return cls(
            settings,
            factory,
            archive,
            transcribe_audio if transcribe_audio is not None else configured_transcriber,
            retry_policy if retry_policy is not None else RetryPolicy(),
            on_update,
            log if log is not None else _unlogged,
            tuple(archive.journals()),
        )

    @property
    def shown(self) -> RecordingState:
        """What the view shows; callers outside the lock use `snapshot`."""
        return self._state.get().state

    def _show(self, state: RecordingState) -> None:
        self._state.set(replace(self._state.get(), state=state))

    @property
    def root(self) -> Path:
        return self.archive.root

    def snapshot(self) -> RecordingState:
        with self._lock:
            return self.shown

    def start_worker(self) -> None:
        with self._lock:
            if self._state.get().worker is None and not self._state.get().closing:
                worker = threading.Thread(target=self._work, name="meeting transcription", daemon=True)
                self._state.set(replace(self._state.get(), worker=worker))
                worker.start()

    def start(self, source: AudioSource = "both", title: str = "Meeting") -> None:
        if not self.settings.api_key or not self.settings.base_url:
            raise OSError("Set OPENAI_BASE_URL and OPENAI_API_KEY before recording a meeting.")
        with self._lock:
            if self._state.get().closing:
                raise OSError("Workspace is shutting down.")
            if self.shown.capturing:
                raise OSError("A meeting is already being recorded. Stop it before starting another.")
            self.start_worker()
            stop = threading.Event()
            capture = threading.Thread(target=self._record, args=(source, title, stop), name="meeting capture", daemon=True)
            self._state.set(
                replace(self._state.get(), stop=stop, state=RecordingState(phase="starting", source=source, title=title), capture=capture)
            )
            capture.start()
        self._emit()

    def stop(self) -> None:
        with self._lock:
            self._state.get().stop.set()
            if self.shown.capturing:
                self._show(replace(self.shown, phase="stopping"))
        self._wake.set()
        self._emit()

    def retry(self) -> None:
        self.start_worker()
        state = self.snapshot()
        if not state.path:
            return
        store = self.archive.open(Path(state.path).parent)
        with self._lock:
            self._state.set(
                replace(self._state.get(), paused=frozendict((key, value) for key, value in self._state.get().paused.items() if key != store.folder))
            )
            if store.folder in self._state.get().scheduled:
                self._state.set(replace(self._state.get(), retry_pending=self._state.get().retry_pending | {store.folder}))
        self._schedule(store)
        try:
            self._publish(store, detail="", phase="finishing")
        except (ValueError, sqlite3.Error) as error:
            raise OSError("The saved meeting journal could not be read. It is still in the meetings folder.") from error

    def close(self, timeout: float = 5) -> None:
        # Stop and journal the final partial second before ending network work.
        # A request already in flight may finish later; its durable audio remains
        # queued if shutdown wins, and no callback can touch a destroyed tray/UI.
        with self._lock:
            self._state.set(replace(self._state.get(), closing=True))
            self._state.get().stop.set()
            capture, worker = self._state.get().capture, self._state.get().worker
        if capture is not None:
            capture.join(timeout)
        self._quit.set()
        self._wake.set()
        self._queue.put(None)
        if worker is not None:
            worker.join(min(1, timeout))
        if capture is not None and capture.is_alive():
            raise OSError("The meeting recorder did not stop in time; already journaled audio and text are saved locally.")

    def _emit(self) -> None:
        with self._emitting:
            with self._lock:
                if self._state.get().closing or self.on_update is None:
                    return
                state, update = self.shown, self.on_update
            update(state)

    def _schedule(self, store: MeetingStore) -> None:
        with self._lock:
            if store.folder not in self._state.get().scheduled and not self._state.get().closing:
                self._state.set(replace(self._state.get(), scheduled=self._state.get().scheduled | {store.folder}))
                self._queue.put(store)
        self._wake.set()

    def _publish(self, store: MeetingStore, *, detail: str | None = None, phase: Phase | None = None) -> None:
        incoming = Publication(store.folder.name, str(store.transcript), store.state(), store.preview())
        with self._lock:
            updated = published(
                self.shown,
                incoming,
                stopping=self._state.get().stop.is_set(),
                paused=self._state.get().paused.get(store.folder),
                phase=phase,
                detail=detail,
            )
            if updated is None:
                return
            self._show(updated)
        self._emit()

    def _record(self, source: AudioSource, title: str, stop: threading.Event) -> None:
        store: MeetingStore | None = None
        journal: _Journal | None = None
        thread: threading.Thread | None = None
        spool = Spool()
        problem = ""
        try:
            store = self.archive.create(source, title)
            with self._lock:
                self._show(replace(self.shown, identity=store.folder.name, path=str(store.transcript)))
            self._publish(store)
            self._schedule(store)
            journal = _Journal(store, spool, self._wake.set, lambda: self._publish(store), self.log)
            thread = threading.Thread(target=journal.run, args=(stop,), name="meeting journal", daemon=True)
            thread.start()

            def ready() -> None:
                # The capture thread only marks the phase; the journal thread publishes it.
                with self._lock:
                    self._show(replace(self.shown, phase="recording"))
                spool.flag()

            self.factory(source).record(stop, spool.put, ready, spool.report)
        except (OSError, ValueError, sqlite3.Error) as error:
            problem = str(error)
        except Exception:
            problem = "Recording stopped unexpectedly. The captured part is saved in the meetings folder."
            self.log(traceback.format_exc())
        finally:
            spool.close()
            if thread is not None:
                thread.join()
            if journal is not None:
                # A storage failure stops capture; report it, not the stop it caused.
                problem = journal.problem or problem
            if problem:
                self.log(f"Meeting recording {store.folder.name if store is not None else '(not created)'} ended: {problem}")
            if store is not None:
                try:
                    store.finish_capture(problem)
                    self._publish(store)
                except OSError, ValueError, sqlite3.Error:
                    # In particular, never claim that a disk-full write succeeded.
                    with self._lock:
                        self._show(replace(self.shown, phase="interrupted", detail=problem or "Recording stopped: local storage is unavailable."))
                    self._emit()
                self._wake.set()
            else:
                with self._lock:
                    self._show(replace(self.shown, phase="interrupted", detail=problem))
                self._emit()

    def _recover(self) -> None:
        for path in self._recovery:
            if self._quit.is_set():
                return
            try:
                store = self.archive.open(path.parent)
                state = store.state()
                if not state.finished:
                    store.interrupt_capture(
                        "Recording was interrupted when Workspace closed. Saved audio has been recovered; capture was not restarted."
                    )
                if not state.complete or not store.transcript.is_file():
                    self._schedule(store)
            except OSError, ValueError, sqlite3.Error:
                # Keep damaged journals for recovery rather than deleting them.
                with self._lock:
                    if not self.shown.visible:
                        self._show(
                            RecordingState(
                                phase="paused",
                                path=str(path.parent / "transcript.md"),
                                detail="A saved meeting could not be recovered. Its journal is still in the meetings folder.",
                            )
                        )
                self._emit()

    def _work(self) -> None:
        self._recover()
        while not self._quit.is_set():
            store = self._queue.get()
            if store is None:
                return
            try:
                self._transcribe(store)
            except Exception as error:
                # Includes a broken connection adapter or a failed export. Do
                # not let a dead worker leave the UI promising transcription.
                detail = "Transcription paused after an error. Saved audio and text remain in the journal; choose Retry."
                if isinstance(error, PermissionError):
                    detail = "Text is saved in the journal. Close the transcript in other apps or restore folder access, then choose Retry."
                with self._lock:
                    self._state.set(replace(self._state.get(), paused=frozendict({**self._state.get().paused, store.folder: detail})))
                    if self.shown.identity == store.folder.name:
                        self._state.get().stop.set()
                        self._show(
                            replace(
                                self.shown,
                                phase="stopping" if self.shown.capturing else "paused",
                                detail=detail,
                            )
                        )
                self._emit()
            finally:
                with self._lock:
                    self._state.set(replace(self._state.get(), scheduled=self._state.get().scheduled - {store.folder}))
                    if store.folder in self._state.get().retry_pending:
                        self._state.set(replace(self._state.get(), retry_pending=self._state.get().retry_pending - {store.folder}))
                        self._schedule(store)

    def _transcribe(self, store: MeetingStore) -> None:
        self._publish(store, phase="finishing")
        failures = 0
        while not self._quit.is_set():
            state = store.state()
            batch = store.batch()
            if batch is None:
                if state.finished:
                    store.export()
                    self._publish(store, detail=state.problem)
                    return
                self._wake.wait(0.5)
                self._wake.clear()
                continue
            # True digital silence needs no model request and cannot hallucinate
            # meeting text; quiet speech is still sent normally.
            # Some endpoints reject tiny uploads. Pad only the request's final
            # fragment; stored duration and timestamps retain the captured length.
            upload = batch.pcm.ljust(RATE * 2, b"\0")
            result = self.transcribe_audio(wav(upload, RATE), context=batch.context) if any(batch.pcm) else ""
            if self._quit.is_set():
                return
            if isinstance(result, Failure):
                retry = self.retry_policy.failed(failures, finished=state.finished)
                detail = "Transcription is unavailable. Audio is saved locally for retry."
                self._publish(store, detail=detail)
                if retry is Exhausted.PAUSED:
                    store.export()
                    with self._lock:
                        self._state.set(replace(self._state.get(), paused=frozendict({**self._state.get().paused, store.folder: detail})))
                    self._publish(store, detail=detail, phase="paused")
                    return
                failures = retry.failures
                self._quit.wait(retry.delay)
                continue
            failures = 0
            store.complete(batch, result)
            try:
                store.export()
            except PermissionError:
                if store.state().finished:
                    raise
                self._publish(store, detail="Text is saved; close the transcript in other apps to refresh its file.")
            else:
                self._publish(store, detail="")

    def describe(self) -> str:
        state = self.snapshot()
        return (
            f"{state.phase}: {state.title}\n{SOURCE_NAMES[state.source]}\n"
            f"Captured {state.seconds:.1f}s; pending {state.pending_seconds:.1f}s.\n"
            f"Transcript: {state.path or 'No recording yet.'}\n{state.detail}"
        )

    def recent(self) -> str:
        entries = (entry for path in reversed(self.archive.journals()[-20:]) if (entry := self._entry(path)) is not None)
        return "\n".join(entries) or "No saved meeting transcripts yet."

    def _entry(self, path: Path) -> str | None:
        """One saved meeting's summary line, or nothing when its journal cannot be read."""
        try:
            store = self.archive.open(path.parent)
            state = store.state()
            return f"{state.title} · {state.frames / RATE:.0f}s · {store.transcript}"
        except OSError, ValueError, sqlite3.Error:
            return None
