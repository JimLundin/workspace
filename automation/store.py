"""Transactional, validated persistence for tasks, inputs, and action outcomes."""

import sqlite3
from collections.abc import Generator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Protocol, assert_never, cast

from pydantic import ConfigDict, TypeAdapter

from automation.task import (
    Action,
    ActionNotApplied,
    ActionOutcome,
    ActionPending,
    ActionReturned,
    ActionSpec,
    ActionUncertain,
    ActionVerified,
    Approval,
    ApprovalDecision,
    Blocked,
    Checkpoint,
    Claim,
    Completed,
    Control,
    Failed,
    GoalRevision,
    Interrupted,
    Outcome,
    Question,
    Reply,
    RequestSource,
    Response,
    RoutineSource,
    Running,
    RunRef,
    Source,
    State,
    Task,
    TaskStatus,
    TextAnswer,
    Until,
    Waiting,
    WaitReason,
    action_finished,
    answered,
    approval_refreshed,
    changed,
    controlled,
    digest,
    finished,
    identifier,
    integer,
    interrupted,
    owns,
    phase,
    progressed,
    redirected,
    started,
    text,
    timestamp,
    variant,
)

SCHEMA_VERSION = 5
_UNBOUND_APPROVAL = "This approval was saved before approvals recorded their operation. Resume the task to review it again."
MAX_PAGE = 1_000
_TASK_COLUMNS: tuple[str, ...] = (
    "id",
    "title",
    "prompt",
    "source",
    "priority",
    "created_at",
    "updated_at",
    "revision",
    "state",
    "checkpoint",
    "goal_revision",
    "phase",
    "routine_id",
    "routine_revision",
    "occurrence_id",
    "wake_at",
)
_TASK_SELECT = ", ".join(_TASK_COLUMNS)
# Queries by profile repeat this exact expression so SQLite uses the index.
_PROFILE = "json_extract(source,'$.profile.kind')"
_PROFILE_INDEX = f"CREATE INDEX IF NOT EXISTS request_profile ON tasks({_PROFILE},created_at,id)"
_ACTION_COLUMNS = "id, task_id, run_id, specification, started_at, updated_at, outcome, outcome_kind, fingerprint"


class _Cursor(Protocol):
    @property
    def rowcount(self) -> int: ...
    def fetchone(self) -> tuple[object, ...] | None: ...
    def fetchall(self) -> list[tuple[object, ...]]: ...


class _Connection(Protocol):
    def execute(self, sql: str, parameters: Sequence[object] = ()) -> _Cursor: ...
    def commit(self) -> None: ...
    def rollback(self) -> None: ...
    def close(self) -> None: ...


# Records are stored in their domain shapes as strict JSON: a variant record's
# `kind` and a payload-free variant's value identify it, and unknown fields are refused.
_STORED = ConfigDict(strict=True, extra="forbid")
_SOURCE = TypeAdapter(Source, config=_STORED)
_STATE = TypeAdapter(State, config=_STORED)
_WAIT = TypeAdapter(WaitReason, config=_STORED)
_REPLY = TypeAdapter(Reply, config=_STORED)
_CHECKPOINT = TypeAdapter(Checkpoint | None, config=_STORED)
# A dataclass adapter takes no config; the optional union carries it, and an absent specification is refused.
_SPECIFICATION = TypeAdapter(ActionSpec | None, config=_STORED)
_OUTCOME = TypeAdapter(ActionOutcome, config=_STORED)


def _stored[T](adapter: TypeAdapter[T], value: T) -> str:
    return adapter.dump_json(value).decode()


def _decoded[T](adapter: TypeAdapter[T], value: object) -> T:
    return adapter.validate_json(text(value, "stored record", maximum=512_000))


def _specification(value: object) -> ActionSpec:
    match _decoded(_SPECIFICATION, value):
        case ActionSpec() as specification:
            return specification
        case None:
            raise ValueError("Invalid stored action specification.")


def _outcome_kind(outcome: ActionOutcome) -> str:
    match outcome:
        case ActionPending():
            return outcome.value
        case ActionReturned() | ActionVerified() | ActionNotApplied() | ActionUncertain():
            return outcome.kind
        case _:
            assert_never(outcome)


def _task_values(task: Task) -> tuple[object, ...]:
    routine = task.source if isinstance(task.source, RoutineSource) else None
    wake = task.state.reason.at if isinstance(task.state, Waiting) and isinstance(task.state.reason, Until) else None
    return (
        task.id,
        task.title,
        task.prompt,
        _stored(_SOURCE, task.source),
        task.priority,
        task.created_at,
        task.updated_at,
        task.revision,
        _stored(_STATE, task.state),
        _stored(_CHECKPOINT, task.checkpoint) if task.checkpoint is not None else None,
        task.goal_revision,
        phase(task.state),
        routine.routine_id if routine is not None else None,
        routine.revision if routine is not None else None,
        routine.occurrence_id if routine is not None else None,
        wake,
    )


def _task(row: tuple[object, ...]) -> Task:
    if len(row) != len(_TASK_COLUMNS):
        raise ValueError("Incomplete stored task.")
    task = Task(
        identifier(row[0], "task identity"),
        text(row[1], "task title", maximum=240),
        text(row[2], "task prompt"),
        _decoded(_SOURCE, row[3]),
        integer(row[4], "task priority", minimum=-10_000, maximum=10_000),
        timestamp(row[5]),
        timestamp(row[6]),
        integer(row[7], "task revision"),
        _decoded(_STATE, row[8]),
        _decoded(_CHECKPOINT, row[9]) if row[9] is not None else None,
        integer(row[10], "goal revision"),
    )
    expected = _task_values(task)
    if row[11:] != expected[11:]:
        raise ValueError("Stored task indexes disagree with task state.")
    return task


def _action(row: tuple[object, ...]) -> Action:
    if len(row) != 9:
        raise ValueError("Incomplete stored action.")
    action = Action(
        identifier(row[0], "action identity"),
        identifier(row[1], "task identity"),
        identifier(row[2], "run identity"),
        _specification(row[3]),
        timestamp(row[4]),
        timestamp(row[5]),
        _decoded(_OUTCOME, row[6]),
    )
    if row[7] != _outcome_kind(action.outcome) or row[8] != action.specification.fingerprint:
        raise ValueError("Stored action indexes disagree with the action.")
    return action


class TaskStore:
    """One durable work database, shared by the exclusive worker and its clients.

    Claiming permits one running task. The controller must additionally await
    an old executor's cancellation acknowledgement before claiming after a
    control or redirection fences that executor. Recovery is only called
    after acquiring exclusive process ownership; it never guesses liveness
    from a timeout or periodically sweeps another worker.
    """

    __slots__ = ("path",)

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection(writing=True) as connection:
            row = connection.execute("PRAGMA user_version").fetchone()
            version = integer(row[0], "work schema version") if row is not None else -1
            if version == SCHEMA_VERSION:
                return
            if version == 2:
                self._migrate_from_version_2(connection)
            if version in (2, 3):
                self._migrate_from_version_3(connection)
            if version in (2, 3, 4):
                self._migrate_from_version_4(connection)
                return
            if version != 0:
                raise ValueError("This work database requires a different Workspace schema version.")
            if connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchone() is not None:
                raise ValueError("The unversioned work database already contains tables.")
            for statement in (
                "CREATE TABLE tasks (id TEXT PRIMARY KEY, title TEXT NOT NULL, prompt TEXT NOT NULL, source TEXT NOT NULL, "
                "priority INTEGER NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL, revision INTEGER NOT NULL, "
                "state TEXT NOT NULL, checkpoint TEXT, goal_revision INTEGER NOT NULL, phase TEXT NOT NULL, "
                "routine_id TEXT, routine_revision INTEGER, occurrence_id TEXT, wake_at REAL)",
                "CREATE UNIQUE INDEX routine_occurrence ON tasks(routine_id,routine_revision,occurrence_id) WHERE routine_id IS NOT NULL",
                "CREATE INDEX runnable_work ON tasks(phase,priority DESC,created_at,id)",
                _PROFILE_INDEX,
                "CREATE TABLE runs (id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id), owner TEXT NOT NULL, "
                "started_at REAL NOT NULL, previous_state TEXT NOT NULL, ended_at REAL, disposition TEXT, UNIQUE(id,task_id))",
                "CREATE TABLE goals (task_id TEXT NOT NULL REFERENCES tasks(id), revision INTEGER NOT NULL, prompt TEXT NOT NULL, "
                "at REAL NOT NULL, PRIMARY KEY(task_id,revision))",
                "CREATE TABLE requests (task_id TEXT NOT NULL REFERENCES tasks(id), id TEXT NOT NULL, goal_revision INTEGER NOT NULL, "
                "run_id TEXT NOT NULL REFERENCES runs(id), request TEXT NOT NULL, at REAL NOT NULL, closed_at REAL, PRIMARY KEY(task_id,id))",
                "CREATE TABLE responses (task_id TEXT NOT NULL REFERENCES tasks(id), request_id TEXT NOT NULL, goal_revision INTEGER NOT NULL, "
                "request TEXT NOT NULL, reply TEXT NOT NULL, at REAL NOT NULL, PRIMARY KEY(task_id,goal_revision,request_id))",
                "CREATE TABLE actions (id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id), run_id TEXT NOT NULL, "
                "specification TEXT NOT NULL, started_at REAL NOT NULL, updated_at REAL NOT NULL, outcome TEXT NOT NULL, "
                "outcome_kind TEXT NOT NULL, fingerprint TEXT NOT NULL, FOREIGN KEY(run_id,task_id) REFERENCES runs(id,task_id))",
                "CREATE INDEX action_identity ON actions(task_id,fingerprint,started_at)",
                "CREATE INDEX unresolved_work ON actions(task_id,outcome_kind,started_at)",
                f"PRAGMA user_version={SCHEMA_VERSION}",
            ):
                connection.execute(statement)

    @staticmethod
    def _migrate_from_version_2(connection: _Connection) -> None:
        """Version 2 packed an approval's operation into its identity and recorded no request profiles.

        Its pending approvals become blocked and its grants are dropped, so each
        operation is reviewed again; nothing is approved without its fingerprint.
        Feed handoffs become general requests: only their feed label is lost.
        """
        blocked = _stored(_STATE, Waiting(Blocked(_UNBOUND_APPROVAL)))
        connection.execute(
            "UPDATE requests SET closed_at=(SELECT updated_at FROM tasks WHERE tasks.id=requests.task_id) "
            "WHERE closed_at IS NULL AND json_extract(request,'$.kind')='approval'"
        )
        connection.execute(
            "UPDATE tasks SET revision=revision+1, state=? WHERE phase='waiting' AND json_extract(state,'$.reason.kind')='approval'",
            (blocked,),
        )
        connection.execute("DELETE FROM responses WHERE json_extract(request,'$.kind')='approval'")
        # Before profiles, the meeting workflow reserved this task identity namespace.
        connection.execute(
            "UPDATE tasks SET source=json_set(source,'$.profile','meeting_followup') "
            "WHERE json_extract(source,'$.kind')='request' AND id LIKE 'meeting-followup-%'"
        )
        connection.execute(
            "UPDATE tasks SET source=json_set(source,'$.profile','general') "
            "WHERE json_extract(source,'$.kind')='request' AND json_extract(source,'$.profile') IS NULL"
        )

    @staticmethod
    def _migrate_from_version_3(connection: _Connection) -> None:
        """Version 3 meeting follow-ups bound their recordings in a separate preparation store.

        Their profiles name no bundle, so those tasks and their journal rows are
        dropped. Published packages and mail files stay on disk, unlisted.
        """
        legacy = "SELECT id FROM tasks WHERE json_extract(source,'$.profile')='meeting_followup'"
        for table in ("actions", "requests", "responses", "goals", "runs"):
            connection.execute(f"DELETE FROM {table} WHERE task_id IN ({legacy})")
        connection.execute(f"DELETE FROM tasks WHERE id IN ({legacy})")

    @staticmethod
    def _migrate_from_version_4(connection: _Connection) -> None:
        """Version 4 hand-built its records; version 5 stores the domain records themselves.

        The conversion is mechanical, so every task, request, reply and action is
        kept: a payload-free variant's `{"kind": ...}` object becomes its value, a
        request's profile fields move into a tagged profile record, and a run
        named by its identity becomes a run reference with its task.
        """
        for table, column, task in (("tasks", "state", "id"), ("runs", "previous_state", "task_id")):
            connection.execute(
                f"UPDATE {table} SET {column}=json_quote(json_extract({column},'$.kind')) "
                f"WHERE json_extract({column},'$.kind') IN ('ready','paused','cancelled')"
            )
            connection.execute(
                f"UPDATE {table} SET {column}=json_set(json_remove({column},'$.run_id'),'$.run',"
                f"json_object('task_id',{task},'run_id',json_extract({column},'$.run_id'))) "
                f"WHERE json_extract({column},'$.kind') IN ('running','interrupted') AND json_extract({column},'$.run_id') IS NOT NULL"
            )
        connection.execute(
            "UPDATE tasks SET source=json_set(json_remove(source,'$.bundle'),'$.profile',"
            "json_object('bundle',json_extract(source,'$.bundle'),'kind','meeting_followup')) "
            "WHERE json_extract(source,'$.kind')='request' AND json_extract(source,'$.profile')='meeting_followup'"
        )
        connection.execute(
            "UPDATE tasks SET source=json_set(json_remove(source,'$.item','$.title'),'$.profile',"
            "json_object('item',json_extract(source,'$.item'),'title',json_extract(source,'$.title'),'kind','feed')) "
            "WHERE json_extract(source,'$.kind')='request' AND json_extract(source,'$.profile')='feed'"
        )
        connection.execute(
            "UPDATE responses SET reply=json_quote(json_extract(reply,'$.kind')) WHERE json_extract(reply,'$.kind') IN ('approved','declined')"
        )
        connection.execute("UPDATE actions SET outcome=json_quote('running') WHERE json_extract(outcome,'$.kind')='running'")
        connection.execute(
            "UPDATE actions SET specification=json_set(specification,'$.verification','none') "
            "WHERE json_extract(specification,'$.verification.kind')='none'"
        )
        connection.execute("DROP INDEX IF EXISTS request_profile")
        connection.execute(_PROFILE_INDEX)
        connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")

    @contextmanager
    def _connection(self, *, writing: bool = False) -> Generator[_Connection]:
        # Narrow SQLite's untyped values to object, then decode every public row.
        connection = cast(_Connection, sqlite3.connect(self.path, timeout=5, isolation_level=None))
        try:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute("PRAGMA busy_timeout=5000")
            connection.execute("BEGIN IMMEDIATE" if writing else "BEGIN")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _read_task(self, connection: _Connection, row: tuple[object, ...]) -> Task:
        task = _task(row)
        if isinstance(task.state, (Running, Interrupted)):
            run = connection.execute("SELECT task_id,owner,started_at FROM runs WHERE id=?", (task.state.run.run_id,)).fetchone()
            if run is None or len(run) != 3 or identifier(run[0], "task identity") != task.id:
                raise ValueError("The stored task references a missing execution.")
            owner, at = identifier(run[1], "worker owner"), timestamp(run[2], "run start")
            if isinstance(task.state, Running) and (task.state.owner != owner or task.state.started_at != at):
                raise ValueError("The stored task disagrees with its execution.")
        if isinstance(task.state, Waiting) and isinstance(task.state.reason, (Question, Approval)):
            request = connection.execute(
                "SELECT goal_revision,request,at,closed_at,run_id FROM requests WHERE task_id=? AND id=?", (task.id, task.state.reason.id)
            ).fetchone()
            if request is None or len(request) != 5 or integer(request[0], "goal revision") != task.goal_revision:
                raise ValueError("The task references a missing input request.")
            if _decoded(_WAIT, request[1]) != task.state.reason or request[3] is not None:
                raise ValueError("The task disagrees with its pending input request.")
            timestamp(request[2], "request time")
            origin = connection.execute("SELECT task_id FROM runs WHERE id=?", (identifier(request[4], "run identity"),)).fetchone()
            if origin is None or len(origin) != 1 or identifier(origin[0], "task identity") != task.id:
                raise ValueError("The pending input references a different execution.")
        return task

    def _get(self, connection: _Connection, identity: str) -> Task | None:
        row = connection.execute(f"SELECT {_TASK_SELECT} FROM tasks WHERE id=?", (identity,)).fetchone()
        return self._read_task(connection, row) if row is not None else None

    def _put(self, connection: _Connection, previous: Task, task: Task) -> None:
        assignments = ", ".join(f"{name}=?" for name in _TASK_COLUMNS[1:])
        values = _task_values(task)
        cursor = connection.execute(f"UPDATE tasks SET {assignments} WHERE id=? AND revision=?", (*values[1:], task.id, previous.revision))
        if cursor.rowcount != 1:
            raise RuntimeError("The task changed during its write transaction.")
        if isinstance(previous.state, Running) and not owns(task, previous.state.run):
            connection.execute("UPDATE runs SET ended_at=?,disposition=? WHERE id=?", (task.updated_at, phase(task.state), previous.state.run.run_id))
        if isinstance(previous.state, Waiting) and isinstance(previous.state.reason, (Question, Approval)) and task.state != previous.state:
            connection.execute("UPDATE requests SET closed_at=? WHERE task_id=? AND id=?", (task.updated_at, task.id, previous.state.reason.id))

    def submit(self, id: str, title: str, prompt: str, source: Source, *, at: float, priority: int = 0) -> Task:
        task = Task(id, title, prompt, source, priority, at, at, 0, TaskStatus.READY, None)
        with self._connection(writing=True) as connection:
            existing = self._get(connection, id)
            if existing is not None:
                if existing.source != source:
                    raise ValueError("That task identity already belongs to a different submission.")
                return existing
            if isinstance(source, RoutineSource):
                row = connection.execute(
                    f"SELECT {_TASK_SELECT} FROM tasks WHERE routine_id=? AND routine_revision=? AND occurrence_id=?",
                    (source.routine_id, source.revision, source.occurrence_id),
                ).fetchone()
                if row is not None:
                    return self._read_task(connection, row)
            marks = ",".join("?" for _ in _TASK_COLUMNS)
            connection.execute(f"INSERT INTO tasks ({_TASK_SELECT}) VALUES ({marks})", _task_values(task))
            connection.execute("INSERT INTO goals(task_id,revision,prompt,at) VALUES (?,?,?,?)", (task.id, 0, task.prompt, at))
        return task

    def get(self, id: str) -> Task | None:
        identifier(id, "task identity")
        with self._connection() as connection:
            return self._get(connection, id)

    def get_many(self, task_ids: tuple[str, ...]) -> tuple[Task, ...]:
        """Read one snapshot in request order, skipping missing IDs and later duplicates."""
        variant(task_ids, tuple, "task identities")
        integer(len(task_ids), "task batch size", maximum=MAX_PAGE)
        unique: dict[str, None] = {identifier(id, "task identity"): None for id in task_ids}
        identities = tuple(unique)
        if not identities:
            return ()
        marks = ",".join("?" for _ in identities)
        with self._connection() as connection:
            rows = connection.execute(f"SELECT {_TASK_SELECT} FROM tasks WHERE id IN ({marks})", identities).fetchall()
            selected: dict[str, Task] = {}
            for row in rows:
                task = self._read_task(connection, row)
                selected[task.id] = task
            return tuple(selected[id] for id in identities if id in selected)

    def list_tasks(self, *, limit: int = 100) -> tuple[Task, ...]:
        integer(limit, "task page size", minimum=1, maximum=MAX_PAGE)
        with self._connection() as connection:
            rows = connection.execute(f"SELECT {_TASK_SELECT} FROM tasks ORDER BY updated_at DESC,id LIMIT ?", (limit,)).fetchall()
            return tuple(self._read_task(connection, row) for row in rows)

    def meeting_followups(self, limit: int) -> tuple[Task, ...]:
        """The newest meeting follow-ups, however many other tasks were updated since."""
        integer(limit, "meeting follow-up page size", minimum=1, maximum=MAX_PAGE)
        with self._connection() as connection:
            rows = connection.execute(
                f"SELECT {_TASK_SELECT} FROM tasks WHERE {_PROFILE}='meeting_followup' ORDER BY created_at DESC,id DESC LIMIT ?", (limit,)
            ).fetchall()
            return tuple(self._read_task(connection, row) for row in rows)

    def active_for_routine(self, routine_id: str) -> Task | None:
        identifier(routine_id, "routine identity")
        with self._connection() as connection:
            row = connection.execute(
                f"SELECT {_TASK_SELECT} FROM tasks WHERE routine_id=? AND phase NOT IN ('completed','failed','cancelled') "
                "ORDER BY created_at,id LIMIT 1",
                (routine_id,),
            ).fetchone()
            return self._read_task(connection, row) if row is not None else None

    def claim(self, owner: str, run_id: str, *, at: float) -> Claim | None:
        identifier(owner, "worker owner")
        identifier(run_id, "run identity")
        timestamp(at)
        with self._connection(writing=True) as connection:
            if connection.execute("SELECT id FROM runs WHERE id=?", (run_id,)).fetchone() is not None:
                return None
            if connection.execute("SELECT id FROM tasks WHERE phase='running' LIMIT 1").fetchone() is not None:
                return None
            row = connection.execute(
                f"SELECT {_TASK_SELECT} FROM tasks WHERE phase IN ('ready','interrupted') OR (phase='waiting' AND wake_at<=?) "
                "ORDER BY priority DESC,created_at,id LIMIT 1",
                (at,),
            ).fetchone()
            if row is None:
                return None
            task = self._read_task(connection, row)
            if isinstance(task.state, Waiting):
                if not isinstance(task.state.reason, Until) or task.state.reason.at > at:
                    raise ValueError("The wake index refers to a task that cannot run.")
                awakened = changed(task, TaskStatus.READY, at=at)
                self._put(connection, task, awakened)
                task = awakened
            previous = task.state
            if previous is not TaskStatus.READY and not isinstance(previous, Interrupted):
                raise ValueError("The runnable index refers to a task that cannot run.")
            run = RunRef(task.id, run_id)
            running = started(task, run, owner, at=at)
            if running is None:
                return None
            connection.execute(
                "INSERT INTO runs(id,task_id,owner,started_at,previous_state) VALUES (?,?,?,?,?)",
                (run_id, task.id, owner, at, _stored(_STATE, previous)),
            )
            self._put(connection, task, running)
            return Claim(running, run, previous)

    def progress(self, run: RunRef, summary: str, *, at: float) -> Task | None:
        Checkpoint(summary, at)
        with self._connection(writing=True) as connection:
            task = self._get(connection, run.task_id)
            result = progressed(task, run, summary, at=at) if task is not None else None
            if result is not None and task is not None:
                self._put(connection, task, result)
            return result

    def finish(self, run: RunRef, outcome: Outcome, *, at: float) -> Task | None:
        timestamp(at)
        variant(outcome, (Completed, Failed, Waiting), "task execution outcome")
        with self._connection(writing=True) as connection:
            task = self._get(connection, run.task_id)
            result = finished(task, run, outcome, at=at) if task is not None else None
            if result is None or task is None:
                return None
            if (
                isinstance(outcome, Completed)
                and connection.execute(
                    "SELECT id FROM actions WHERE task_id=? AND outcome_kind IN ('running','uncertain','returned') LIMIT 1",
                    (task.id,),
                ).fetchone()
                is not None
            ):
                return None
            if isinstance(outcome, Waiting) and isinstance(outcome.reason, (Question, Approval)):
                if connection.execute("SELECT id FROM requests WHERE task_id=? AND id=?", (task.id, outcome.reason.id)).fetchone() is not None:
                    raise ValueError("An input request identity cannot be reused.")
                connection.execute(
                    "INSERT INTO requests(task_id,id,goal_revision,run_id,request,at) VALUES (?,?,?,?,?,?)",
                    (task.id, outcome.reason.id, task.goal_revision, run.run_id, _stored(_WAIT, outcome.reason), at),
                )
            self._put(connection, task, result)
            return result

    def interrupt(self, run: RunRef, reason: str, *, at: float) -> Task | None:
        Interrupted(run, reason)
        timestamp(at)
        with self._connection(writing=True) as connection:
            task = self._get(connection, run.task_id)
            result = interrupted(task, run, reason, at=at) if task is not None else None
            if result is not None and task is not None:
                self._put(connection, task, result)
            return result

    def control(self, id: str, command: Control, *, at: float) -> Task | None:
        identifier(id, "task identity")
        timestamp(at)
        variant(command, Control, "task control")
        with self._connection(writing=True) as connection:
            task = self._get(connection, id)
            result = controlled(task, command, at=at) if task is not None else None
            if result is not None and task is not None:
                self._put(connection, task, result)
            return result

    def control_conversation(self, conversation_id: str, command: Control, *, at: float) -> int:
        """Control every matching request task without depending on a UI page."""
        identifier(conversation_id, "conversation identity")
        timestamp(at)
        variant(command, Control, "task control")
        count, cursor = 0, ""
        with self._connection(writing=True) as connection:
            while True:
                rows = connection.execute(
                    f"SELECT {_TASK_SELECT} FROM tasks WHERE id>? AND phase NOT IN ('completed','cancelled') "
                    "AND json_extract(source,'$.kind')='request' AND json_extract(source,'$.conversation_id')=? "
                    "ORDER BY id LIMIT 100",
                    (cursor, conversation_id),
                ).fetchall()
                if not rows:
                    return count
                for row in rows:
                    task = self._read_task(connection, row)
                    if not isinstance(task.source, RequestSource) or task.source.conversation_id != conversation_id:
                        raise ValueError("The conversation index disagrees with the task source.")
                    result = controlled(task, command, at=at)
                    if result is not None:
                        self._put(connection, task, result)
                        count += 1
                    cursor = task.id

    def revise(self, task_id: str, prompt: str, *, at: float) -> Task | None:
        identifier(task_id, "task identity")
        text(prompt, "task prompt")
        timestamp(at)
        with self._connection(writing=True) as connection:
            task = self._get(connection, task_id)
            if task is None:
                return None
            result = redirected(task, prompt, at=at)
            self._put(connection, task, result)
            connection.execute("INSERT INTO goals(task_id,revision,prompt,at) VALUES (?,?,?,?)", (task.id, result.goal_revision, prompt, at))
            return result

    def answer(self, id: str, request_id: str, reply: Reply, *, at: float) -> Task | None:
        identifier(id, "task identity")
        identifier(request_id, "request identity")
        timestamp(at)
        variant(reply, (TextAnswer, ApprovalDecision), "input reply")
        with self._connection(writing=True) as connection:
            task = self._get(connection, id)
            update = answered(task, request_id, reply, at=at) if task is not None else None
            if update is None or task is None:
                return None
            result, response = update
            connection.execute(
                "INSERT INTO responses(task_id,request_id,goal_revision,request,reply,at) VALUES (?,?,?,?,?,?)",
                (task.id, request_id, task.goal_revision, _stored(_WAIT, response.request), _stored(_REPLY, reply), at),
            )
            self._put(connection, task, result)
            return result

    def refresh_approval(self, task_id: str, request_id: str, *, at: float) -> Task | None:
        """Request a fresh live preview without creating an approval response."""
        identifier(task_id, "task identity")
        identifier(request_id, "request identity")
        timestamp(at)
        with self._connection(writing=True) as connection:
            task = self._get(connection, task_id)
            result = approval_refreshed(task, request_id, at=at) if task is not None else None
            if result is not None and task is not None:
                self._put(connection, task, result)
            return result

    def request_run(self, task_id: str, request_id: str) -> RunRef | None:
        """Identify the run that produced this exact, still-pending input."""
        identifier(task_id, "task identity")
        identifier(request_id, "request identity")
        with self._connection() as connection:
            task = self._get(connection, task_id)
            if task is None or not isinstance(task.state, Waiting) or not isinstance(task.state.reason, (Question, Approval)):
                return None
            if task.state.reason.id != request_id:
                return None
            row = connection.execute("SELECT run_id FROM requests WHERE task_id=? AND id=?", (task_id, request_id)).fetchone()
            if row is None or len(row) != 1:
                raise ValueError("The pending input has no originating execution.")
            return RunRef(task_id, identifier(row[0], "run identity"))

    def responses(self, task_id: str) -> tuple[Response, ...]:
        """Current-goal replies only; a redirection cannot inherit old approvals."""
        identifier(task_id, "task identity")
        with self._connection() as connection:
            task = self._get(connection, task_id)
            if task is None:
                return ()
            rows = connection.execute(
                "SELECT request,reply,at,request_id FROM responses WHERE task_id=? AND goal_revision=? ORDER BY at,request_id LIMIT ?",
                (task_id, task.goal_revision, MAX_PAGE + 1),
            ).fetchall()
        if len(rows) > MAX_PAGE:
            raise ValueError("Too many input responses to recover this task.")
        replies: list[Response] = []
        for row in rows:
            if len(row) != 4:
                raise ValueError("Incomplete stored input response.")
            request = _decoded(_WAIT, row[0])
            if not isinstance(request, (Question, Approval)) or request.id != identifier(row[3], "request identity"):
                raise ValueError("Invalid stored input request.")
            replies.append(Response(request, _decoded(_REPLY, row[1]), timestamp(row[2])))
        return tuple(replies)

    def revisions(self, task_id: str, *, limit: int = 100) -> tuple[GoalRevision, ...]:
        identifier(task_id, "task identity")
        integer(limit, "goal page size", minimum=1, maximum=MAX_PAGE)
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT revision,prompt,at FROM goals WHERE task_id=? ORDER BY revision DESC LIMIT ?", (task_id, limit)
            ).fetchall()
        return tuple(GoalRevision(integer(row[0], "goal revision"), text(row[1], "goal prompt"), timestamp(row[2])) for row in reversed(rows))

    def recover(self, owner: str, *, at: float) -> tuple[Task, ...]:
        """Reconcile abandoned runs after the caller acquired exclusive ownership.

        The owner is this process's fresh identity. A run already belonging to
        it is never swept; callers must not invoke recovery while a peer lives.
        """
        identifier(owner, "worker owner")
        timestamp(at)
        recovered: list[Task] = []
        with self._connection(writing=True) as connection:
            rows = connection.execute(f"SELECT {_TASK_SELECT} FROM tasks WHERE phase='running' ORDER BY created_at,id").fetchall()
            for row in rows:
                task = self._read_task(connection, row)
                if not isinstance(task.state, Running):
                    raise ValueError("The running index disagrees with task state.")
                if task.state.owner == owner:
                    continue
                result = interrupted(task, task.state.run, "Execution stopped before its outcome was saved.", at=at)
                if result is not None:
                    self._put(connection, task, result)
                    recovered.append(result)
        return tuple(recovered)

    def _read_action(self, connection: _Connection, row: tuple[object, ...]) -> Action:
        action = _action(row)
        run = connection.execute("SELECT task_id FROM runs WHERE id=?", (action.run_id,)).fetchone()
        if run is None or len(run) != 1 or identifier(run[0], "task identity") != action.task_id:
            raise ValueError("The stored action references a missing execution.")
        return action

    def begin_action(self, run: RunRef, action_id: str, specification: ActionSpec, *, at: float) -> Action | None:
        action = Action(action_id, run.task_id, run.run_id, specification, at, at, ActionPending.RUNNING)
        with self._connection(writing=True) as connection:
            task = self._get(connection, run.task_id)
            if task is None or not owns(task, run):
                return None
            if connection.execute("SELECT id FROM actions WHERE id=?", (action_id,)).fetchone() is not None:
                return None
            if (
                connection.execute(
                    "SELECT id FROM actions WHERE task_id=? AND fingerprint=? AND outcome_kind IN ('running','uncertain') LIMIT 1",
                    (run.task_id, specification.fingerprint),
                ).fetchone()
                is not None
            ):
                return None
            connection.execute(
                "INSERT INTO actions(id,task_id,run_id,specification,started_at,updated_at,outcome,outcome_kind,fingerprint) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    action_id,
                    run.task_id,
                    run.run_id,
                    _stored(_SPECIFICATION, specification),
                    at,
                    at,
                    _stored(_OUTCOME, action.outcome),
                    "running",
                    specification.fingerprint,
                ),
            )
        return action

    def finish_action(self, action_id: str, outcome: ActionOutcome, *, at: float) -> Action | None:
        identifier(action_id, "action identity")
        timestamp(at)
        variant(outcome, (ActionPending, ActionReturned, ActionVerified, ActionNotApplied, ActionUncertain), "action outcome")
        with self._connection(writing=True) as connection:
            row = connection.execute(f"SELECT {_ACTION_COLUMNS} FROM actions WHERE id=?", (action_id,)).fetchone()
            if row is None:
                return None
            action = self._read_action(connection, row)
            result = action_finished(action, outcome, at=at)
            if result is None:
                return None
            connection.execute(
                "UPDATE actions SET updated_at=?,outcome=?,outcome_kind=? WHERE id=?",
                (result.updated_at, _stored(_OUTCOME, result.outcome), _outcome_kind(result.outcome), action_id),
            )
            return result

    def actions(self, task_id: str, *, limit: int = 100) -> tuple[Action, ...]:
        identifier(task_id, "task identity")
        integer(limit, "action page size", minimum=1, maximum=MAX_PAGE)
        with self._connection() as connection:
            rows = connection.execute(
                f"SELECT {_ACTION_COLUMNS} FROM actions WHERE task_id=? ORDER BY started_at DESC,id DESC LIMIT ?", (task_id, limit)
            ).fetchall()
            return tuple(self._read_action(connection, row) for row in reversed(rows))

    def unresolved_actions(self, task_id: str) -> tuple[Action, ...]:
        identifier(task_id, "task identity")
        with self._connection() as connection:
            rows = connection.execute(
                f"SELECT {_ACTION_COLUMNS} FROM actions WHERE task_id=? AND outcome_kind IN ('running','uncertain') ORDER BY started_at,id LIMIT ?",
                (task_id, MAX_PAGE + 1),
            ).fetchall()
            if len(rows) > MAX_PAGE:
                raise ValueError("Too many uncertain actions to recover this task.")
            return tuple(self._read_action(connection, row) for row in rows)

    def unverified_actions(self, task_id: str) -> tuple[Action, ...]:
        """All actions still needing verification, independent of display pages."""
        identifier(task_id, "task identity")
        with self._connection() as connection:
            rows = connection.execute(
                f"SELECT {_ACTION_COLUMNS} FROM actions WHERE task_id=? AND outcome_kind IN ('running','uncertain','returned') "
                "ORDER BY started_at,id LIMIT ?",
                (task_id, MAX_PAGE + 1),
            ).fetchall()
            if len(rows) > MAX_PAGE:
                raise ValueError("Too many unverified actions to complete this task.")
            return tuple(self._read_action(connection, row) for row in rows)

    def action_since(self, task_id: str, fingerprint: str, *, after: float) -> bool:
        """Any attempted action consumes an approval, independently of UI pages."""
        identifier(task_id, "task identity")
        digest(fingerprint)
        timestamp(after)
        with self._connection() as connection:
            row = connection.execute(
                f"SELECT {_ACTION_COLUMNS} FROM actions WHERE task_id=? AND fingerprint=? AND started_at>=? ORDER BY started_at,id LIMIT 1",
                (task_id, fingerprint, after),
            ).fetchone()
            if row is None:
                return False
            self._read_action(connection, row)
            return True
