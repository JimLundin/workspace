"""What the conversation window shows of durable work, decided from each journal snapshot.

`present` is pure: given what was presented and a new snapshot, it returns
what is presented now and the window effects that show it, in order. The
work agent commits the state, then performs the effects.
"""

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from itertools import accumulate, chain
from typing import assert_never

from contracts.agent_session import AgentRequest
from contracts.feed_origin import FeedRequest, Initiation
from contracts.task import (
    Blocked,
    Completed,
    Failed,
    FeedHandoff,
    Interrupted,
    Question,
    Running,
    Task,
    TaskStatus,
    Until,
    Waiting,
    requested,
    terminal,
)
from contracts.work_snapshot import WorkSnapshot


def in_conversation(task: Task, conversation_id: str | None) -> bool:
    return task.source.conversation_id == conversation_id


def source_is_automatic(task: Task) -> bool:
    """Notification admission owns this durable identity namespace."""
    return isinstance(task.source.profile, FeedHandoff) and task.id.startswith("workspace-notification:")


def active(task: Task) -> bool:
    match task.state:
        case TaskStatus.PAUSED | Waiting(Blocked() | Until()):
            return False
        case _:
            return not terminal(task.state)


def new_turn(previous: Task, task: Task) -> bool:
    """A changed goal or execution break starts a turn; user input continues it."""
    if task.goal_revision != previous.goal_revision:
        return True
    match previous.state, task.state:
        case Waiting(), Waiting():
            return False
        case Waiting(Question()), _:
            return False
        case Waiting(), _:
            return True
        case Running(run=before) | Interrupted(run=before), Running(run=after):
            return before != after
        case _:
            return False


def turn_ended(task: Task) -> bool:
    match task.state:
        case Waiting(reason):
            match reason:
                case Blocked() | Until():
                    return True
                case Question():
                    return False
                case _:
                    assert_never(reason)
        case Completed() | Failed() | TaskStatus.PAUSED | TaskStatus.CANCELLED:
            return True
        case TaskStatus.READY | Running() | Interrupted():
            return False
        case _:
            assert_never(task.state)


def chronological(task: Task) -> tuple[float, str]:
    return task.created_at, task.id


@dataclass(frozen=True, slots=True)
class Presented:
    settled: frozendict[str, int] = frozendict()
    """The revision of each task already presented."""
    started: bool = False
    """Whether this process has taken its first snapshot of existing work."""
    displayed: Task | None = None
    queued: frozenset[str] = frozenset()
    """Tasks the window lists as waiting their turn."""
    rejected_input: tuple[str, str] | None = None
    """A reply the journal refused, for the displayed task's request."""


@dataclass(frozen=True, slots=True)
class Open:
    """Create the window if it isn't open."""


@dataclass(frozen=True, slots=True)
class Withdraw:
    """Withdraw the window's input request, if the window is open."""


@dataclass(frozen=True, slots=True)
class Leave:
    """The displayed task left the conversation: stop its live output and finish its turn, if the window is open."""


@dataclass(frozen=True, slots=True)
class EndTurn:
    """Finish the window's current turn."""


@dataclass(frozen=True, slots=True)
class Begin:
    """Start a turn; the window's live output follows it."""

    title: str
    queued: bool = False
    source: FeedRequest | None = None


@dataclass(frozen=True, slots=True)
class Step:
    text: str


@dataclass(frozen=True, slots=True)
class Done:
    text: str


@dataclass(frozen=True, slots=True)
class Say:
    text: str


@dataclass(frozen=True, slots=True)
class Problem:
    text: str


@dataclass(frozen=True, slots=True)
class Ask:
    """Ask for the task's reply in the window."""

    task_id: str
    request: AgentRequest


@dataclass(frozen=True, slots=True)
class Retract:
    """A refused reply: withdraw it, say so and ask again, if the window is open."""

    ask: Ask


@dataclass(frozen=True, slots=True)
class Queue:
    prompt: str


type Effect = Open | Withdraw | Leave | EndTurn | Begin | Step | Done | Say | Problem | Ask | Retract | Queue

OPEN, WITHDRAW, LEAVE, END_TURN = Open(), Withdraw(), Leave(), EndTurn()


def present(state: Presented, snapshot: WorkSnapshot, conversation: str | None) -> tuple[Presented, Iterator[Effect]]:
    """What is presented after `snapshot`, and the effects that show it, lazily and in order."""
    retracted = _retracted(state.rejected_input, snapshot)
    tasks = sorted((task for task in snapshot.tasks if in_conversation(task, conversation)), key=chronological)
    task_ids = {task.id for task in tasks}
    settled = frozendict((identity, revision) for identity, revision in state.settled.items() if identity in task_ids)
    if not state.started:
        # Finished work is history at startup, not news: presenting it
        # replayed every old blocked or failed task as a warning balloon
        # and beep each time Workspace restarted.
        settled = settled | {task.id: task.revision for task in tasks if not active(task)}
    displayed, queued = state.displayed, state.queued
    left = displayed is not None and displayed.id not in task_ids
    if left:
        displayed, queued = None, frozenset[str]()
    shown = _shown(displayed, tasks, settled)
    previous = (displayed, *(None for _ in shown[1:]))
    queued_before = tuple(accumulate(zip(previous, shown, strict=False), lambda queued, step: _queued_after(*step, queued), initial=queued))
    queued = queued_before[-1]
    settled = settled | {task.id: task.revision for task in shown if not active(task)}
    displayed = shown[-1] if shown and active(shown[-1]) else None
    room = max(0, 100 - len(queued))
    waiting = tuple(task for task in tasks if active(task) and (displayed is None or task.id != displayed.id) and task.id not in queued)[:room]
    effects = chain(
        retracted,
        (WITHDRAW, LEAVE) if left else (),
        chain.from_iterable(_display(*step) for step in zip(previous, queued_before, shown, strict=False)),
        (Queue(task.prompt) for task in waiting),
    )
    return Presented(settled, True, displayed, queued | {task.id for task in waiting}, None), effects


def _retracted(rejected: tuple[str, str] | None, snapshot: WorkSnapshot) -> tuple[Effect, ...]:
    """A refused reply is retracted and asked again, if its request still stands."""
    if rejected is None:
        return ()
    task_id, request_id = rejected
    task = next((task for task in snapshot.tasks if task.id == task_id), None)
    request = requested(task) if task is not None else None
    # A failure is only recorded for the displayed task, and publishing restores it before redisplaying.
    if task is None or request is None or request.id != request_id:
        return ()
    return (Retract(Ask(task.id, AgentRequest(request, request.detail, task.updated_at))),)


def _shown(displayed: Task | None, tasks: Sequence[Task], settled: Mapping[str, int]) -> tuple[Task, ...]:
    """The tasks shown in turn: the displayed one, then each unpresented one, until one is still active."""
    first = next((task for task in tasks if displayed is not None and task.id == displayed.id), None)
    unpresented = (task for task in tasks if settled.get(task.id) != task.revision and (first is None or task.id != first.id))
    turns = (first, *unpresented) if first is not None else tuple(unpresented)
    last = next((index for index, task in enumerate(turns) if active(task)), len(turns) - 1)
    return turns[: last + 1]


def _queued_after(previous: Task | None, task: Task, queued: frozenset[str]) -> frozenset[str]:
    if task == previous:
        return queued
    if turn_ended(task):
        return frozenset()
    return queued - {task.id} if previous is None or previous.id != task.id else queued


def _display(previous: Task | None, queued: frozenset[str], task: Task) -> Iterator[Effect]:
    """Show `task`, which becomes the displayed one."""
    if task == previous:
        return
    match task.source.profile:
        case FeedHandoff(item, title):
            initiation = Initiation.AUTOMATIC if source_is_automatic(task) else Initiation.REQUESTED
            source: FeedRequest | None = FeedRequest(item, title, initiation=initiation)
        case _:
            source = None
    yield OPEN
    if previous is None or previous.id != task.id:
        yield WITHDRAW
        yield Begin(source.title if source is not None else task.prompt, queued=task.id in queued, source=source)
    elif new_turn(previous, task):
        yield WITHDRAW
        if active(task):
            yield END_TURN
            yield Begin(f"Continue: {task.title}", source=source)
    if task.checkpoint is not None and (previous is None or previous.checkpoint != task.checkpoint):
        yield Step(task.checkpoint.summary)
    yield from _status(task)


def _status(task: Task) -> Iterator[Effect]:
    if requested(task) is None:
        yield WITHDRAW
    match task.state:
        case TaskStatus.READY:
            yield Step("Queued.")
        case Running():
            pass
        case Interrupted(_, reason):
            yield Step(f"Recovering interrupted work: {reason}")
        case Waiting(reason):
            match reason:
                case Question() as question:
                    yield Ask(task.id, AgentRequest(question, question.detail, task.updated_at))
                case Blocked(explanation):
                    yield Say(explanation) if source_is_automatic(task) else Problem(explanation)
                case Until(_, explanation):
                    yield Say(f"Waiting: {explanation}")
                case _:
                    assert_never(reason)
        case Completed(result, _):
            yield Done(result)
        case Failed(reason):
            yield Say(reason) if source_is_automatic(task) else Problem(reason)
        case TaskStatus.CANCELLED:
            yield Done("Stopped.")
        case TaskStatus.PAUSED:
            yield Say("Paused. Resume this task from Work.")
        case _:
            assert_never(task.state)
    if turn_ended(task):
        yield END_TURN
