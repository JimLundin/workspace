"""A durable, bounded queue of audio and an atomically refreshed Markdown transcript.

Text replaces its audio in one SQLite transaction. Freed audio pages are erased
and reclaimed; completed meetings retain text and timing, not a full recording.
"""

import os
import time
import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import datetime
from pathlib import Path
from typing import Final

from pydantic import TypeAdapter

from assistant.recording_state import Batch, StoredState, duration, source_name
from automation import journal
from automation.capture import AudioSource
from automation.meetings import CONVERSATION, MEETING, Ended, InProgress, Meeting, MeetingConversation, TranscriptEntry, TranscriptState, UnknownEnd
from winapi.pcm import RATE, quiet_tail

MAX_PENDING_BYTES: Final = 256 * 1024 * 1024
MIN_CHUNK_SECONDS: Final = 20
MAX_CHUNK_SECONDS: Final = 30
_END = TypeAdapter(float | None)


def _replace_transcript(temporary: Path, transcript: Path) -> None:
    # Ordinary Windows readers often omit FILE_SHARE_DELETE. Their short-lived
    # handles must not turn an otherwise successful transcription into a failure.
    deadline = time.monotonic() + 2
    while True:
        try:
            temporary.replace(transcript)
            return
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.05)


def _integer(value: object) -> int:
    if not isinstance(value, int):
        raise ValueError("Invalid meeting timing in the local journal.")
    return value


def _text(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("Invalid text in the local meeting journal.")
    return value


class BacklogFullError(OSError):
    """The last block was saved, but capture must stop before storing another."""


class MeetingStore:
    __slots__ = ("connect", "folder", "max_pending_bytes", "publish")

    def __init__(
        self,
        folder: Path,
        *,
        max_pending_bytes: int = MAX_PENDING_BYTES,
        publish: Callable[[Path, Path], None] = _replace_transcript,
        connect: journal.Connect = journal.open_journal,
    ) -> None:
        # Location, storage bound, publication and connection lifetime are the
        # cohesive journal policy. Readers and writers use the same interface.
        self.connect = connect
        self.folder = folder
        self.max_pending_bytes = max_pending_bytes
        self.publish = publish

    @property
    def transcript(self) -> Path:
        return self.folder / "transcript.md"

    def reading(self) -> AbstractContextManager[journal.Connection]:
        """One snapshot of this recording's journal; callers validate each column before use."""
        if not (self.folder / "session.sqlite3").is_file():
            raise FileNotFoundError("The native meeting journal is unavailable.")
        return journal.reading(self.folder / "session.sqlite3", self.connect)

    def writing(self) -> AbstractContextManager[journal.Connection]:
        return journal.writing(self.folder / "session.sqlite3", self.connect)

    @classmethod
    def create(
        cls,
        root: Path,
        source: AudioSource,
        title: str = "Meeting",
        *,
        max_pending_bytes: int = MAX_PENDING_BYTES,
        publish: Callable[[Path, Path], None] = _replace_transcript,
    ) -> MeetingStore:
        now = time.time()
        folder = root / (datetime.fromtimestamp(now).strftime("%Y-%m-%d_%H-%M-%S_") + uuid.uuid4().hex[:8])
        folder.mkdir(parents=True)
        store = cls(folder, max_pending_bytes=max_pending_bytes, publish=publish)
        with store.writing() as connection:
            connection.execute(
                "CREATE TABLE meeting (id INTEGER PRIMARY KEY CHECK (id=1), title TEXT NOT NULL, source TEXT NOT NULL, "
                "started REAL NOT NULL, frames INTEGER NOT NULL DEFAULT 0, pending INTEGER NOT NULL DEFAULT 0, "
                "finished INTEGER NOT NULL DEFAULT 0, problem TEXT NOT NULL DEFAULT '', "
                "revision INTEGER NOT NULL DEFAULT 0, exported_revision INTEGER NOT NULL DEFAULT -1)"
            )
            connection.execute("CREATE TABLE audio (start INTEGER PRIMARY KEY, frames INTEGER NOT NULL, quiet INTEGER NOT NULL, pcm BLOB NOT NULL)")
            connection.execute("CREATE TABLE segments (start INTEGER PRIMARY KEY, end INTEGER NOT NULL, text TEXT NOT NULL)")
            connection.execute(
                "INSERT INTO meeting (id, title, source, started) VALUES (1, ?, ?, ?)", (" ".join(title.split())[:160] or "Meeting", source, now)
            )
        store.export()
        return store

    def state(self) -> StoredState:
        with self.reading() as connection:
            return self._state(connection)

    def _state(self, connection: journal.Connection) -> StoredState:
        row = connection.execute(
            "SELECT title, source, started, frames, pending, finished, problem, revision, exported_revision FROM meeting WHERE id=1",
        ).fetchone()
        ending = (
            connection.execute("SELECT at FROM capture_end WHERE id=1").fetchone()
            if connection.execute("SELECT name FROM sqlite_master WHERE name='capture_end'").fetchone() is not None
            else None
        )
        if row is None or row[1] not in ("both", "microphone") or not isinstance(row[2], (int, float)):
            raise ValueError("The local meeting journal is incomplete.")
        return StoredState(
            _text(row[0]),
            row[1],
            float(row[2]),
            _integer(row[3]),
            _integer(row[4]),
            finished=bool(row[5]),
            problem=_text(row[6]),
            revision=_integer(row[7]),
            exported_revision=_integer(row[8]),
            ended_at=_END.validate_python(ending[0] if ending is not None else None, strict=True),
        )

    def append(self, pcm: bytes) -> None:
        if not pcm:
            return
        if len(pcm) % 2 or len(pcm) > RATE * 2:
            raise ValueError("Meeting audio must be written in blocks of at most one second.")
        frames = len(pcm) // 2
        with self.writing() as connection:
            row = connection.execute("SELECT frames, finished FROM meeting WHERE id=1").fetchone()
            if row is None or row[1]:
                raise ValueError("Cannot append audio to a finished meeting.")
            connection.execute(
                "INSERT INTO audio (start, frames, quiet, pcm) VALUES (?, ?, ?, ?)", (_integer(row[0]), frames, int(quiet_tail(pcm)), pcm)
            )
            connection.execute("UPDATE meeting SET frames=frames+?, pending=pending+?, revision=revision+1 WHERE id=1", (frames, frames))
            pending = connection.execute("SELECT pending FROM meeting WHERE id=1").fetchone()
        if pending is not None and _integer(pending[0]) * 2 >= self.max_pending_bytes:
            raise BacklogFullError("Recording stopped because untranscribed audio reached its storage limit. Saved audio can be retried.")

    def finish_capture(self, problem: str = "", *, at: float | None = None) -> None:
        """Persist the observed capture end, independently of audio duration and export time."""
        self._finish(problem, time.time() if at is None else at)

    def interrupt_capture(self, problem: str) -> None:
        """Recovery cannot reconstruct the time a dead capture actually stopped."""
        self._finish(problem, None)

    def _finish(self, problem: str, at: float | None) -> None:
        with self.writing() as connection:
            # Repeated stop/recovery must never move the original end timestamp.
            changed = connection.execute("UPDATE meeting SET finished=1, problem=?, revision=revision+1 WHERE id=1 AND finished=0", (problem,))
            if changed.rowcount:
                connection.execute("CREATE TABLE IF NOT EXISTS capture_end (id INTEGER PRIMARY KEY CHECK(id=1), at REAL)")
                connection.execute("INSERT INTO capture_end (id, at) VALUES (1, ?)", (at,))

    def meeting(self) -> Meeting:
        return self._meeting(self.state())

    def _meeting(self, saved: StoredState) -> Meeting:
        period = (
            InProgress(saved.started)
            if not saved.finished
            else UnknownEnd(saved.started)
            if saved.ended_at is None
            else Ended(saved.started, saved.ended_at)
        )
        observed = Meeting(
            self.folder.name,
            saved.title,
            period,
            saved.source,
            saved.frames / RATE,
            saved.pending / RATE,
            str(self.transcript.absolute()),
            TranscriptState.COMPLETE if saved.finished and not saved.pending else TranscriptState.PENDING,
            saved.revision,
            saved.problem,
        )
        # Existing dataclass instances are trusted by Pydantic. The IO round trip
        # revalidates constrained journal numbers before publishing typed values.
        return MEETING.validate_json(MEETING.dump_json(observed))

    def conversation(self, offset: int = 0, limit: int = 50) -> MeetingConversation:
        """Read a bounded page of ordered conversation batches from the authoritative journal."""
        if offset < 0 or not 1 <= limit <= 100:
            raise ValueError("Meeting conversation pages require a nonnegative offset and 1-100 entries.")
        with self.reading() as connection:
            meeting = self._meeting(self._state(connection))
            count = connection.execute("SELECT COUNT(*) FROM segments WHERE text!=''").fetchone()
            rows = connection.execute(
                "SELECT start, end, text FROM segments WHERE text!='' ORDER BY start LIMIT ? OFFSET ?", (limit, offset)
            ).fetchall()
        total = _integer(count[0]) if count is not None else 0
        entries = tuple(TranscriptEntry(_integer(row[0]) / RATE, _integer(row[1]) / RATE, _text(row[2])) for row in rows)
        observed = MeetingConversation(meeting, entries, total, offset + len(entries) if offset + len(entries) < total else None)
        return CONVERSATION.validate_json(CONVERSATION.dump_json(observed))

    def batch(self) -> Batch | None:
        with self.reading() as connection:
            # Capture may append its tail and finish between these queries.
            # One read snapshot keeps the completion flag with the same audio.
            rows = connection.execute("SELECT start, frames, quiet, pcm FROM audio ORDER BY start LIMIT ?", (MAX_CHUNK_SECONDS,)).fetchall()
            complete = connection.execute("SELECT finished FROM meeting WHERE id=1").fetchone()
            prior = connection.execute("SELECT text FROM segments WHERE text!='' ORDER BY start DESC LIMIT 1").fetchone()
        if not rows:
            return None
        frames, parts = 0, bytearray()
        for row in rows:
            if not isinstance(row[3], bytes) or len(row[3]) != _integer(row[1]) * 2:
                raise ValueError("An audio block in the meeting journal is incomplete.")
            if _integer(row[0]) != _integer(rows[0][0]) + frames:
                raise ValueError("An audio block is missing from the meeting journal.")
            parts.extend(row[3])
            frames += _integer(row[1])
            if frames >= MIN_CHUNK_SECONDS * RATE and (row[2] or frames >= MAX_CHUNK_SECONDS * RATE):
                break
        else:
            if not complete or not complete[0]:
                return None
        return Batch(_integer(rows[0][0]), bytes(parts), _text(prior[0])[-600:] if prior else "")

    def complete(self, batch: Batch, text: str) -> None:
        with self.writing() as connection:
            # Retrying after a write/export failure must not duplicate a segment
            # or decrement the pending count a second time.
            if connection.execute("SELECT start FROM segments WHERE start=?", (batch.start,)).fetchone() is not None:
                return
            connection.execute("INSERT INTO segments (start, end, text) VALUES (?, ?, ?)", (batch.start, batch.end, text.strip()))
            connection.execute("DELETE FROM audio WHERE start>=? AND start<?", (batch.start, batch.end))
            connection.execute("UPDATE meeting SET pending=pending-?, revision=revision+1 WHERE id=1", (len(batch.pcm) // 2,))

    def preview(self) -> str:
        with self.reading() as connection:
            rows = connection.execute("SELECT start, end, text FROM segments WHERE text!='' ORDER BY start DESC LIMIT 8").fetchall()
        return "\n\n".join(f"**{duration(_integer(row[0]) / RATE)}**  {_text(row[2])[:2000]}" for row in reversed(rows))

    def observation(self) -> tuple[Meeting, str]:
        """One bounded native-event/preview snapshot for catalog intake."""
        with self.reading() as connection:
            meeting = self._meeting(self._state(connection))
            rows = connection.execute("SELECT start, text FROM segments WHERE text!='' ORDER BY start DESC LIMIT 8").fetchall()
        preview = "\n\n".join(f"{duration(_integer(row[0]) / RATE)}  {_text(row[1])[:2000]}" for row in reversed(rows))
        return meeting, preview[:6000]

    def export(self) -> None:
        temporary = self.transcript.with_suffix(".tmp")
        state = self.state()
        if state.revision == state.exported_revision and self.transcript.is_file():
            return  # preserve corrections the user made to a completed transcript
        status = "Recording" if not state.finished else "Transcription pending" if state.pending else "Saved"
        # The transcription worker owns export after creation, so one atomic
        # replacement is sufficient; capture only writes to the SQLite journal.
        try:
            with temporary.open("w", encoding="utf-8", newline="\n") as output, self.reading() as connection:
                output.write(f"# {state.title}\n\n{datetime.fromtimestamp(state.started).isoformat(timespec='seconds')}\n\n")
                if state.ended_at is not None:
                    output.write(f"Ended {datetime.fromtimestamp(state.ended_at).isoformat(timespec='seconds')}\n\n")
                output.write(f"{source_name(state.source)} · {duration(state.frames / RATE)} captured · {status}\n\n")
                if state.problem:
                    output.write(f"> {state.problem}\n\n")
                for row in connection.execute("SELECT start, end, text FROM segments ORDER BY start"):
                    if text := _text(row[2]):
                        output.write(f"## {duration(_integer(row[0]) / RATE)} - {duration(_integer(row[1]) / RATE)}\n\n{text}\n\n")
                if state.pending:
                    output.write(f"*{duration(state.pending / RATE)} of audio is saved locally and awaiting transcription.*\n")
                output.flush()
                os.fsync(output.fileno())
            self.publish(temporary, self.transcript)
            with self.writing() as connection:
                connection.execute("UPDATE meeting SET exported_revision=? WHERE id=1", (state.revision,))
        finally:
            temporary.unlink(missing_ok=True)


class MeetingArchive:
    """Create and reopen journals with the same storage and publication policy."""

    __slots__ = ("max_pending_bytes", "publish", "root")

    def __init__(
        self,
        root: Path,
        *,
        max_pending_bytes: int = MAX_PENDING_BYTES,
        publish: Callable[[Path, Path], None] = _replace_transcript,
    ) -> None:
        self.root, self.max_pending_bytes, self.publish = root, max_pending_bytes, publish

    def create(self, source: AudioSource, title: str = "Meeting") -> MeetingStore:
        return MeetingStore.create(self.root, source, title, max_pending_bytes=self.max_pending_bytes, publish=self.publish)

    def open(self, folder: Path) -> MeetingStore:
        return MeetingStore(folder, max_pending_bytes=self.max_pending_bytes, publish=self.publish)

    def journals(self) -> tuple[Path, ...]:
        return tuple(sorted(self.root.glob("*/session.sqlite3")))
