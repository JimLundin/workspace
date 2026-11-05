"""Explicit long-running recording, independent of dictation, model work and the UI.

The real-time capture thread only hands audio to a bounded in-memory spool. A
journal thread writes it one second at a time and publishes progress every few
seconds. A separate worker transcribes 20-30 second chunks, retries outages, and
resumes pending text work after a restart. Restarting Workspace never resumes
microphone or computer-audio capture.
"""

import contextlib
import queue
import sqlite3
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Final, Protocol

from assistant.llm import Failure, Settings, transcribe, wav
from assistant.meeting_store import MeetingArchive, MeetingStore
from assistant.recording_state import Exhausted, Phase, Publication, RecordingState, RetryPolicy, published, source_name
from automation.capture import AudioSource
from usage import DIRECTORY
from winapi.pcm import RATE


class Transcriber(Protocol):
    def __call__(self, audio: bytes, *, context: str) -> str | Failure: ...


class Capture(Protocol):
    def record(self, stop: threading.Event, consume: Callable[[bytes], None], ready: Callable[[], None]) -> None: ...


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
    flagged: bool = False
    closed: bool = False


class Spool:
    """A bounded handover from the real-time capture thread to the journal thread.

    `put` never waits for storage: it holds the lock only to append. A block that
    would exceed the bound is refused, which ends the recording.
    """

    __slots__ = ("_blocks", "_closed", "_condition", "_flagged", "_size", "limit")

    def __init__(self, limit: int = RATE * 2 * SPOOL_SECONDS) -> None:
        self.limit = limit
        self._condition = threading.Condition()
        self._blocks: deque[bytes] = deque()
        self._size = 0
        self._flagged = self._closed = False

    def put(self, pcm: bytes) -> None:
        if len(pcm) % 2:
            raise ValueError("The capture device returned an invalid audio block.")
        with self._condition:
            if self._size + len(pcm) > self.limit:
                raise SpoolFullError(
                    f"Recording stopped: saving fell more than {self.limit // (RATE * 2)} s behind the audio devices. "
                    "The captured part has been saved."
                )
            self._blocks.append(pcm)
            self._size += len(pcm)
            self._condition.notify()

    def flag(self) -> None:
        """Ask the journal thread to publish the current state soon."""
        with self._condition:
            self._flagged = True
            self._condition.notify()

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._condition.notify()

    def take(self, timeout: float) -> Handover:
        with self._condition:
            self._condition.wait_for(lambda: self._blocks or self._flagged or self._closed, timeout)
            pcm = b"".join(self._blocks)
            self._blocks.clear()
            self._size = 0
            taken = Handover(pcm, flagged=self._flagged, closed=self._closed)
            self._flagged = False
            return taken


class _Writer:
    """Cut handed-over audio into the journal's one-second blocks."""

    __slots__ = ("buffer", "store")

    def __init__(self, store: MeetingStore) -> None:
        self.store = store
        self.buffer = bytearray()

    def feed(self, pcm: bytes) -> bool:
        self.buffer.extend(pcm)
        appended = False
        while len(self.buffer) >= RATE * 2:
            block = bytes(self.buffer[: RATE * 2])
            del self.buffer[: RATE * 2]
            self.store.append(block)
            appended = True
        return appended

    def finish(self) -> None:
        block = bytes(self.buffer)
        self.buffer.clear()
        self.store.append(block)


class _Journal:
    """The capture's storage owner: writes spooled audio and paces its publication."""

    __slots__ = ("changed", "problem", "publish", "spool", "store")

    def __init__(self, store: MeetingStore, spool: Spool, changed: Callable[[], None], publish: Callable[[], None]) -> None:
        self.store, self.spool, self.changed, self.publish = store, spool, changed, publish
        self.problem = ""

    def run(self, stop: threading.Event) -> None:
        writer = _Writer(self.store)
        published, dirty = time.monotonic() - PUBLISH_SECONDS, False
        try:
            while True:
                due = published + PUBLISH_SECONDS - time.monotonic()
                taken = self.spool.take(max(0.0, due) if dirty else PUBLISH_SECONDS)
                if writer.feed(taken.pcm):
                    self.changed()
                    dirty = True
                now = time.monotonic()
                # A phase change publishes even when capture has already ended.
                if taken.flagged or (dirty and now - published >= PUBLISH_SECONDS and not taken.closed):
                    self.publish()
                    published, dirty = now, False
                if taken.closed:
                    writer.finish()
                    self.changed()
                    return
        except (OSError, ValueError, sqlite3.Error) as error:
            self.problem = str(error)
        except Exception:
            self.problem = "Recording stopped unexpectedly. The captured part is saved in the meetings folder."
        # Saving failed: end capture, and never store audio captured after the failure.
        stop.set()


class Meetings:
    __slots__ = (
        "_capture",
        "_closing",
        "_emitting",
        "_lock",
        "_paused",
        "_queue",
        "_quit",
        "_recovery",
        "_retry_pending",
        "_scheduled",
        "_state",
        "_stop",
        "_wake",
        "_worker",
        "archive",
        "factory",
        "on_meeting",
        "on_update",
        "retry_policy",
        "settings",
        "transcribe_audio",
    )

    def __init__(  # noqa: PLR0913 - injected collaborators and callbacks
        self,
        settings: Settings,
        factory: Callable[[AudioSource], Capture],
        *,
        archive: MeetingArchive | None = None,
        on_update: Callable[[RecordingState], None] | None = None,
        transcribe_audio: Transcriber | None = None,
        retry_policy: RetryPolicy | None = None,
        on_meeting: Callable[[MeetingStore], None] | None = None,
    ) -> None:
        # Capture, transcription, storage and their independent publications
        # are effect dependencies; no callback owns another owner's progress.
        self.settings, self.factory = settings, factory
        self.archive = archive if archive is not None else MeetingArchive(DIRECTORY / "meetings")

        def configured_transcriber(audio: bytes, *, context: str) -> str | Failure:
            return transcribe(settings, audio, context=context)

        self.transcribe_audio: Transcriber = transcribe_audio if transcribe_audio is not None else configured_transcriber
        self.retry_policy = retry_policy if retry_policy is not None else RetryPolicy()
        self.on_update = on_update
        self.on_meeting = on_meeting
        self._lock = threading.RLock()
        # Serializes publications in state order without holding `_lock`: the
        # view takes its own locks, and capture or snapshot() must never wait for them.
        self._emitting = threading.RLock()
        self._state = RecordingState()
        self._stop, self._quit, self._wake = threading.Event(), threading.Event(), threading.Event()
        self._queue: queue.Queue[MeetingStore | None] = queue.Queue()
        self._scheduled: set[Path] = set()
        self._paused: dict[Path, str] = {}
        self._retry_pending: set[Path] = set()
        self._capture: threading.Thread | None = None
        self._worker: threading.Thread | None = None
        self._closing = False
        self._recovery = self.archive.journals()

    @property
    def root(self) -> Path:
        return self.archive.root

    def snapshot(self) -> RecordingState:
        with self._lock:
            return self._state

    def start_worker(self) -> None:
        with self._lock:
            if self._worker is None and not self._closing:
                self._worker = threading.Thread(target=self._work, name="meeting transcription", daemon=True)
                self._worker.start()

    def start(self, source: AudioSource = "both", title: str = "Meeting") -> None:
        if not self.settings.api_key or not self.settings.base_url:
            raise OSError("Set OPENAI_BASE_URL and OPENAI_API_KEY before recording a meeting.")
        with self._lock:
            if self._closing:
                raise OSError("Workspace is shutting down.")
            if self._state.capturing:
                raise OSError("A meeting is already being recorded. Stop it before starting another.")
            self.start_worker()
            self._stop = threading.Event()
            self._state = RecordingState(phase="starting", source=source, title=title)
            self._capture = threading.Thread(target=self._record, args=(source, title, self._stop), name="meeting capture", daemon=True)
            self._capture.start()
        self._emit()

    def stop(self) -> None:
        with self._lock:
            self._stop.set()
            if self._state.capturing:
                self._state = replace(self._state, phase="stopping")
        self._wake.set()
        self._emit()

    def retry(self) -> None:
        self.start_worker()
        state = self.snapshot()
        if not state.path:
            return
        store = self.archive.open(Path(state.path).parent)
        with self._lock:
            self._paused.pop(store.folder, None)
            if store.folder in self._scheduled:
                self._retry_pending.add(store.folder)
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
            self._closing = True
            self._stop.set()
            capture, worker = self._capture, self._worker
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
                if self._closing or self.on_update is None:
                    return
                state, update = self._state, self.on_update
            update(state)

    def _observe_meeting(self, store: MeetingStore) -> None:
        if self.on_meeting is not None:
            self.on_meeting(store)

    def _schedule(self, store: MeetingStore) -> None:
        with self._lock:
            if store.folder not in self._scheduled and not self._closing:
                self._scheduled.add(store.folder)
                self._queue.put(store)
        self._wake.set()

    def _publish(self, store: MeetingStore, *, detail: str | None = None, phase: Phase | None = None) -> None:
        incoming = Publication(store.folder.name, str(store.transcript), store.state(), store.preview())
        with self._lock:
            updated = published(
                self._state, incoming, stopping=self._stop.is_set(), paused=self._paused.get(store.folder), phase=phase, detail=detail
            )
            if updated is None:
                return
            self._state = updated
        self._emit()

    def _record(self, source: AudioSource, title: str, stop: threading.Event) -> None:
        store: MeetingStore | None = None
        journal: _Journal | None = None
        thread: threading.Thread | None = None
        spool = Spool()
        problem = ""
        try:
            store = self.archive.create(source, title)
            self._observe_meeting(store)
            with self._lock:
                self._state = replace(self._state, identity=store.folder.name, path=str(store.transcript))
            self._publish(store)
            self._schedule(store)
            journal = _Journal(store, spool, self._wake.set, lambda: self._publish(store))
            thread = threading.Thread(target=journal.run, args=(stop,), name="meeting journal", daemon=True)
            thread.start()

            def ready() -> None:
                # The capture thread only marks the phase; the journal thread publishes it.
                with self._lock:
                    self._state = replace(self._state, phase="recording")
                spool.flag()

            self.factory(source).record(stop, spool.put, ready)
        except (OSError, ValueError, sqlite3.Error) as error:
            problem = str(error)
        except Exception:
            problem = "Recording stopped unexpectedly. The captured part is saved in the meetings folder."
        finally:
            spool.close()
            if thread is not None:
                thread.join()
            if journal is not None:
                # A storage failure stops capture; report it, not the stop it caused.
                problem = journal.problem or problem
            if store is not None:
                try:
                    store.finish_capture(problem)
                    self._observe_meeting(store)
                    self._publish(store)
                except OSError, ValueError, sqlite3.Error:
                    # In particular, never claim that a disk-full write succeeded.
                    with self._lock:
                        self._state = replace(self._state, phase="interrupted", detail=problem or "Recording stopped: local storage is unavailable.")
                    self._emit()
                self._wake.set()
            else:
                with self._lock:
                    self._state = replace(self._state, phase="interrupted", detail=problem)
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
                self._observe_meeting(store)
                if not state.complete or not store.transcript.is_file():
                    self._schedule(store)
            except OSError, ValueError, sqlite3.Error:
                # Keep damaged journals for recovery rather than deleting them.
                with self._lock:
                    if not self._state.visible:
                        self._state = RecordingState(
                            phase="paused",
                            path=str(path.parent / "transcript.md"),
                            detail="A saved meeting could not be recovered. Its journal is still in the meetings folder.",
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
                    self._paused[store.folder] = detail
                    if self._state.identity == store.folder.name:
                        self._stop.set()
                        self._state = replace(
                            self._state,
                            phase="stopping" if self._state.capturing else "paused",
                            detail=detail,
                        )
                self._emit()
            finally:
                with self._lock:
                    self._scheduled.discard(store.folder)
                    if store.folder in self._retry_pending:
                        self._retry_pending.remove(store.folder)
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
                    self._observe_meeting(store)
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
                        self._paused[store.folder] = detail
                    self._publish(store, detail=detail, phase="paused")
                    return
                failures = retry.failures
                self._quit.wait(retry.delay)
                continue
            failures = 0
            store.complete(batch, result)
            self._observe_meeting(store)
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
            f"{state.phase}: {state.title}\n{source_name(state.source)}\n"
            f"Captured {state.seconds:.1f}s; pending {state.pending_seconds:.1f}s.\n"
            f"Transcript: {state.path or 'No recording yet.'}\n{state.detail}"
        )

    def recent(self) -> str:
        entries: list[str] = []
        for path in reversed(self.archive.journals()[-20:]):
            with contextlib.suppress(OSError, ValueError, sqlite3.Error):
                store = self.archive.open(path.parent)
                state = store.state()
                entries.append(f"{state.title} · {state.frames / RATE:.0f}s · {store.transcript}")
        return "\n".join(entries) or "No saved meeting transcripts yet."
