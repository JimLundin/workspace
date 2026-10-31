"""The canvas owner: one local document, its observations and its policy.

`WorkCanvas` is the only writer of `canvas.sqlite3`. Qt serializes every
observation, command, answer and user edit through it; other threads only
read. Callers render the returned document and deliver the returned notices.
"""

import hashlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from typing import assert_never
from uuid import uuid4

from pydantic import TypeAdapter

from assistant.agent_session import Snapshot
from assistant.canvas_activity import (
    ROOT_CONTEXT,
    Attention,
    CanvasActivity,
    CanvasInstruction,
    CanvasQuestion,
    CanvasRequest,
    CanvasResearch,
    CanvasRun,
    TaskRequest,
    important_changes,
    session_activity,
    settle_session,
    settle_tasks,
    task_activity,
)
from assistant.work_canvas_commands import (
    CanvasCommand,
    CanvasRefused,
    CanvasResponse,
    CanvasUpdated,
    ReadCanvas,
    UpdateCanvas,
    edited,
    revision,
    snapshot,
)
from assistant.work_canvas_edits import UserEdit, user_edited
from assistant.work_canvas_model import (
    DOCUMENT,
    CanvasDocument,
    hidden_ids,
    observe_activity,
    result_document,
)
from assistant.work_window import WorkSnapshot
from automation import journal
from automation.personal_work import Catalog, SourceKind, WorkState, WorkThread
from automation.task import Blocked, Task, TextAnswer, Waiting, phase

_EVIDENCE = TypeAdapter(tuple[tuple[str, str], ...])
_FINISHED = ("completed", "failed", "cancelled")


@dataclass(frozen=True, slots=True)
class Announcement:
    title: str
    target: str


@dataclass(frozen=True, slots=True)
class CanvasChange:
    document: CanvasDocument
    notice: Announcement | None = None


@dataclass(frozen=True, slots=True)
class Queued:
    document: CanvasDocument


@dataclass(frozen=True, slots=True)
class NotQueued:
    """The binding stays saved, so retrying or startup recovery reuses it."""

    document: CanvasDocument
    reason: str


@dataclass(frozen=True, slots=True)
class ResumeTask:
    task_id: str


class Investigating(Enum):
    ALREADY = "already"


type Continuation = Queued | NotQueued | ResumeTask | Investigating


@dataclass(frozen=True, slots=True)
class AnswerQuestion:
    request: CanvasRequest


class SpeechRoute(Enum):
    INSTRUCT = "instruct"
    FALLBACK = "fallback"


type Speech = AnswerQuestion | SpeechRoute


class WorkCanvas:
    # Mutable owner state: the latest observations that later policy compares
    # against. Callers serialize use on Qt, so these need no lock.
    __slots__ = ("_autonomous", "_catalog", "_queue", "_session", "_task_activity", "_tasks", "path")

    def __init__(self, path: Path, queue: Callable[[CanvasRun], None], *, autonomous: bool) -> None:
        self.path: Path = path
        self._queue: Callable[[CanvasRun], None] = queue
        self._autonomous: bool = autonomous
        self._catalog: Catalog | None = None
        self._tasks: tuple[Task, ...] = ()
        self._session: tuple[CanvasActivity, ...] | None = None
        self._task_activity: tuple[CanvasActivity, ...] = ()
        path.parent.mkdir(parents=True, exist_ok=True)
        with journal.writing(path) as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS canvas (id INTEGER PRIMARY KEY CHECK(id=1), payload BLOB NOT NULL)")
            connection.execute("INSERT OR IGNORE INTO canvas VALUES (1, ?)", (DOCUMENT.dump_json(CanvasDocument()),))
            document = _loaded(connection)
            retained_document = result_document(document)
            if retained_document != document:
                # Remove retired execution projections once at startup. Their
                # full action history belongs to the separate execution ledger.
                connection.execute("UPDATE canvas SET payload=? WHERE id=1", (DOCUMENT.dump_json(retained_document),))

    def _observed_catalog(self) -> Catalog:
        return self._catalog or Catalog()

    def read(self) -> CanvasDocument:
        with journal.reading(self.path) as connection:
            document = _loaded(connection)
        return result_document(document)

    def _save(self, document: CanvasDocument) -> None:
        checked = result_document(DOCUMENT.validate_python(document))
        with journal.writing(self.path) as connection:
            connection.execute("UPDATE canvas SET payload=? WHERE id=1", (DOCUMENT.dump_json(checked),))

    def _persist(self, previous: CanvasDocument, current: CanvasDocument) -> CanvasDocument:
        if previous != current:
            self._save(current)
        return current

    def observe_session(self, session: Snapshot) -> CanvasDocument | None:
        """Mirror conversation questions; None when the session activity is unchanged."""
        activity = session_activity(session)
        if activity == self._session:
            return None
        self._session = activity
        previous = self.read()
        document = observe_activity(previous, activity)
        return self._persist(previous, replace(document, activity=settle_session(document.activity, session)))

    def observe_work(self, observed: WorkSnapshot) -> CanvasChange:
        self._tasks = observed.tasks
        previous = self.read()
        updates = task_activity(observed.tasks, previous.runs)
        known = frozenset(item.id for item in (*self._task_activity, *(self._session or ())))
        self._task_activity = updates
        document = observe_activity(previous, updates)
        rejected = frozenset(TaskRequest(problem.task_id, problem.request_id) for problem in observed.reply_problems)
        document = self._persist(previous, replace(document, activity=settle_tasks(document.activity, observed.tasks, rejected)))
        hidden = hidden_ids(self._observed_catalog(), document)
        # Announce each new result or question once, and never inside dismissed work.
        additions = tuple(item for item in updates if item.id not in known and item.id not in hidden)
        notice = Announcement(additions[-1].title, additions[-1].id) if additions else None
        return CanvasChange(self._investigate(document), notice)

    def observe_catalog(self, catalog: Catalog) -> CanvasChange:
        previous, self._catalog = self._catalog, catalog
        document = self._investigate(self.read())
        # The first catalog is a silent baseline; later state changes are announced.
        changes = important_changes(previous, catalog) if previous is not None else ()
        if not changes:
            return CanvasChange(document)
        latest = next(work for work in catalog.works if work.id == changes[-1])
        return CanvasChange(document, Announcement("Canvas updated · " + latest.definition.title, latest.id))

    def _investigate(self, previous: CanvasDocument) -> CanvasDocument:
        """Queue bounded research for changed evidence, saving each binding before its task."""
        if not self._autonomous or self._catalog is None:
            return previous
        document = self._persist(previous, retained(previous, self._tasks))
        for run in pending(self._catalog, document, self._tasks):
            document = replace(document, runs=(*document.runs, run))
            self._save(document)
            try:
                self._queue(run)
            except ValueError:
                # Queue refusal must not mark this evidence as investigated.
                document = replace(document, runs=tuple(binding for binding in document.runs if binding.task_id != run.task_id))
                self._save(document)
                break
        return document

    def start(self, run: CanvasRun) -> Queued | NotQueued:
        """Save the binding before queueing, so a crash or refusal keeps the user's direction."""
        previous = self.read()
        document = previous if run in previous.runs else self._persist(previous, replace(previous, runs=(*previous.runs, run)))
        try:
            self._queue(run)
        except (OSError, ValueError) as error:
            return NotQueued(document, str(error))
        return Queued(document)

    def continue_work(self, work_id: str) -> Continuation:
        """Continue one work without duplicating its unfinished investigation."""
        document = self.read()
        active = frozendict((task.id, task) for task in self._tasks if phase(task.state) not in _FINISHED)
        binding = next((run for run in reversed(document.runs) if run.work_id == work_id and run.task_id in active), None)
        if binding is None:
            return self.start(CanvasRun("canvas:" + uuid4().hex, work_id))
        match active[binding.task_id].state:
            case Waiting(reason=Blocked()):
                return ResumeTask(binding.task_id)
            case _:
                return Investigating.ALREADY

    def command(self, request: CanvasCommand) -> CanvasResponse:
        document = self.read()
        match request:
            case ReadCanvas():
                return snapshot(document, self._observed_catalog(), request)
            case UpdateCanvas():
                try:
                    current = edited(document, request, self._observed_catalog())
                except ValueError as error:
                    return CanvasRefused(str(error))
                self._save(current)
                return CanvasUpdated(request.expected_revision, revision(current), changed=current != document)

    def commit(self, edit: UserEdit) -> CanvasDocument:
        """Persist one user edit to the latest document; an invalid edit raises ValueError and saves nothing."""
        document = self.read()
        return self._persist(document, user_edited(document, self._observed_catalog(), edit))

    def waiting(self) -> tuple[CanvasQuestion, ...]:
        """Visible questions still waiting for the user, in canvas order."""
        document = self.read()
        hidden = hidden_ids(self._observed_catalog(), document)
        return tuple(
            item for item in document.activity if isinstance(item, CanvasQuestion) and item.reply is Attention.WAITING and item.id not in hidden
        )

    def settled(self, document: CanvasDocument) -> frozenset[str]:
        """Questions the conversation should stop presenting: answered, closed or dismissed."""
        hidden = hidden_ids(self._observed_catalog(), document)
        return frozenset(
            item.id for item in document.activity if isinstance(item, CanvasQuestion) and (item.reply is not Attention.WAITING or item.id in hidden)
        )

    def speech(self, selected: str | None, *, visible: bool) -> Speech:
        """Speech answers the selected waiting question, instructs the open canvas, or falls back."""
        if not visible:
            return SpeechRoute.FALLBACK
        question = next((item for item in self.waiting() if item.id == selected), None)
        return AnswerQuestion(question.request) if question is not None else SpeechRoute.INSTRUCT

    def answer(self, request: CanvasRequest, value: TextAnswer, deliver: Callable[[CanvasRequest, TextAnswer], bool]) -> CanvasDocument | None:
        """Deliver only to a visible waiting question; record the reply once delivery accepts it."""
        if not any(item.request == request for item in self.waiting()) or not deliver(request, value):
            return None
        document = self.read()
        activity = tuple(
            replace(item, reply=value) if isinstance(item, CanvasQuestion) and item.request == request else item for item in document.activity
        )
        return self._persist(document, replace(document, activity=activity))


def _loaded(connection: journal.Connection) -> CanvasDocument:
    observed: object = connection.execute("SELECT payload FROM canvas WHERE id=1").fetchone()
    match observed:
        case (bytes() as payload,):
            return DOCUMENT.validate_json(payload)
        case _:
            raise ValueError("The local canvas document is unavailable.")


def retained(document: CanvasDocument, tasks: Sequence[Task]) -> CanvasDocument:
    terminal = frozenset(task.id for task in tasks if phase(task.state) in _FINISHED)
    latest = frozendict((run.work_id, run.task_id) for run in document.runs if run.evidence is not None)
    # Completed contributions already carry their work identity in activity.
    # Retain the latest evidence cursor plus every unresolved/manual binding.
    runs = tuple(
        run
        for run in document.runs
        if (run.work_id != ROOT_CONTEXT or run.task_id not in terminal)
        and (run.evidence is None or run.task_id not in terminal or latest.get(run.work_id) == run.task_id)
    )
    return replace(document, runs=runs)


def evidence(work: WorkThread, catalog: Catalog) -> str | None:
    linked = frozenset(link.source_id for link in work.links)
    included = linked
    # Rendered child emails/messages can change while their conversation's
    # summary stays the same. Documents we register ourselves do not retrigger.
    while True:
        revised = included | frozenset(source.id for source in catalog.sources if source.parent_id in included)
        if revised == included:
            break
        included = revised
    observed = tuple(
        sorted(
            (source.id, source.revision)
            for source in catalog.sources
            if source.id in included and source.kind not in (SourceKind.DOCUMENT, SourceKind.WEB_PAGE)
        )
    )
    return hashlib.sha256(_EVIDENCE.dump_json(observed)).hexdigest() if observed else None


def pending(catalog: Catalog, document: CanvasDocument, tasks: Sequence[Task]) -> tuple[CanvasRun, ...]:
    known = frozendict((task.id, phase(task.state)) for task in tasks)
    busy = frozenset(run.work_id for run in document.runs if known.get(run.task_id) not in _FINISHED)
    automatic = sum(run.evidence is not None and known.get(run.task_id) not in _FINISHED for run in document.runs)
    capacity = max(0, 3 - automatic)
    # Bindings are retained by the execution journal's bounded watcher. Avoid
    # silently losing question routing when its retention budget is exhausted.
    capacity = min(capacity, max(0, 500 - len(document.runs)))
    candidates: tuple[CanvasRun, ...] = ()
    for work in catalog.works:
        if work.definition.state is not WorkState.ACTIVE or work.id in busy:
            continue
        current = evidence(work, catalog)
        if current is None or any(run.work_id == work.id and run.evidence == current for run in document.runs):
            continue
        identity = hashlib.sha256((work.id + "\0" + current).encode()).hexdigest()
        candidates = (*candidates, CanvasRun("canvas:auto:" + identity, work.id, CanvasResearch(current)))
        if len(candidates) == capacity:
            break
    return candidates if capacity else ()


def instruction_prompt(run: CanvasRun) -> str:
    """Keep the user's exact direction durable alongside its canvas context."""
    match run.intent:
        case CanvasInstruction(text=instruction):
            context = (
                "Its scope is the whole canvas. Read work_canvas_read to inspect the existing bubbles before acting. "
                if run.work_id == ROOT_CONTEXT
                else f"Its context bubble is {run.work_id}. Read work_canvas_read to inspect that bubble, "
                "its ancestors, connected references and contents before acting. "
            )
            return (
                instruction + "\n\n"
                "This instruction was submitted from the local desktop canvas. "
                + context
                + "There is one shared canvas; organize work using nested bubbles on it. "
                "Use the available browser and document tools to investigate, and work_canvas_update to add only meaningful "
                "findings, references, drafts and questions to the appropriate bubbles. Keep routine fetch attempts in execution history. "
                "The request itself and reports of actions taken are execution history, not canvas content. "
                "Editing positions or relationships changes the existing canvas directly without adding a report bubble. "
                "For substantive new work, choose or create a meaningful context, and place the useful results there. "
                "Ask for clarification when needed, and continue the same work after the user answers. "
                "The user's instruction above determines what actions are authorized."
            )
        case CanvasResearch():
            raise ValueError("A research run has no user instruction.")
        case _:
            assert_never(run.intent)
