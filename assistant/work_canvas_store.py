"""The Qt canvas owner saves its local document separately from agent work."""

import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

from assistant.agent_session import Snapshot
from assistant.canvas_activity import (
    CanvasActivity,
    TaskRequest,
    session_activity,
    settle_session,
    settle_tasks,
    task_activity,
)
from assistant.work_canvas_model import DOCUMENT, CanvasDocument, observe_activity, result_document
from assistant.work_window import WorkSnapshot


class CanvasStore:
    __slots__ = ("path",)

    def __init__(self, path: Path) -> None:
        self.path: Path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS canvas (id INTEGER PRIMARY KEY CHECK(id=1), payload BLOB NOT NULL)")
            connection.execute("INSERT OR IGNORE INTO canvas VALUES (1, ?)", (DOCUMENT.dump_json(CanvasDocument()),))
            document = self.loaded(connection)
            retained = result_document(document)
            if retained != document:
                # Remove retired execution projections once at startup. Their
                # full action history belongs to the separate execution ledger.
                connection.execute("UPDATE canvas SET payload=? WHERE id=1", (DOCUMENT.dump_json(retained),))

    def read(self) -> CanvasDocument:
        with self.connection() as connection:
            document = self.loaded(connection)
        return result_document(document)

    def loaded(self, connection: sqlite3.Connection) -> CanvasDocument:
        observed: object = connection.execute("SELECT payload FROM canvas WHERE id=1").fetchone()
        match observed:
            case (bytes() as payload,):
                return DOCUMENT.validate_json(payload)
            case _:
                raise ValueError("The local canvas document is unavailable.")

    def save(self, document: CanvasDocument) -> None:
        checked = result_document(DOCUMENT.validate_python(document))
        with self.connection() as connection:
            connection.execute("UPDATE canvas SET payload=? WHERE id=1", (DOCUMENT.dump_json(checked),))

    def capture(self, updates: tuple[CanvasActivity, ...]) -> CanvasDocument:
        """The Qt owner serializes captures and placements; keep both in one row."""
        document = self.read()
        updated = observe_activity(document, updates)
        if updated != document:
            self.save(updated)
        return updated

    def observe_session(self, session: Snapshot) -> CanvasDocument:
        previous = self.read()
        document = observe_activity(previous, session_activity(session))
        return self.persist(previous, replace(document, activity=settle_session(document.activity, session)))

    def observe_tasks(self, snapshot: WorkSnapshot) -> CanvasDocument:
        previous = self.read()
        document = observe_activity(previous, task_activity(snapshot.tasks, previous.runs))
        rejected = frozenset(TaskRequest(problem.task_id, problem.request_id) for problem in snapshot.reply_problems)
        return self.persist(previous, replace(document, activity=settle_tasks(document.activity, snapshot.tasks, rejected)))

    def persist(self, previous: CanvasDocument, current: CanvasDocument) -> CanvasDocument:
        if previous != current:
            self.save(current)
        return current

    @contextmanager
    def connection(self) -> Generator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        try:
            with connection:
                yield connection
        finally:
            connection.close()
