"""Shared canvas activity, exact clarification identity and task projections.

App observations remain context for the agent. Clarifications and material work
changes are the interaction surface; ordinary app arrivals do not become alerts.
"""

from dataclasses import dataclass, replace
from enum import Enum
from typing import Annotated, Literal, assert_never

from pydantic import Field

import contracts.task
from contracts.feed_origin import App, Origin
from contracts.personal_work import Catalog, Identity, Title

type Body = Annotated[str, Field(max_length=32000)]
type Timestamp = Annotated[float, Field(ge=0, allow_inf_nan=False)]
ROOT_CONTEXT = "canvas:root"


def question_body(question: str, detail: str) -> str:
    # The full short question is already in the heading. Long questions retain
    # their complete wording in the body despite the bounded title projection.
    return (question + "\n\n" + detail if len(question) > 240 else detail)[:32000]


@dataclass(frozen=True, slots=True)
class TaskRequest:
    task_id: Identity
    request_id: Identity
    kind: Literal["task"] = "task"


@dataclass(frozen=True, slots=True)
class SessionRequest:
    session_id: Identity
    request_id: Identity
    kind: Literal["session"] = "session"


type CanvasRequest = Annotated[TaskRequest | SessionRequest, Field(discriminator="kind")]


class Attention(Enum):
    WAITING = "waiting"
    CLOSED = "closed"


type CanvasReply = Attention | contracts.task.TextAnswer


@dataclass(frozen=True, slots=True)
class CanvasResearch:
    evidence: str | None = None
    kind: Literal["research"] = "research"


@dataclass(frozen=True, slots=True)
class CanvasInstruction:
    text: Body
    kind: Literal["instruction"] = "instruction"

    def __post_init__(self) -> None:
        contracts.task.text(self.text, "canvas instruction", maximum=32000)


@dataclass(frozen=True, slots=True)
class CanvasIntake:
    evidence: str
    kind: Literal["intake"] = "intake"


type CanvasIntent = Annotated[CanvasResearch | CanvasInstruction | CanvasIntake, Field(discriminator="kind")]


@dataclass(frozen=True, slots=True)
class CanvasRun:
    task_id: Identity
    work_id: Identity
    intent: CanvasIntent = CanvasResearch()

    @property
    def evidence(self) -> str | None:
        match self.intent:
            case CanvasResearch(evidence=evidence) | CanvasIntake(evidence=evidence):
                return evidence
            case CanvasInstruction():
                return None
            case _:
                assert_never(self.intent)


class ActionState(Enum):
    RUNNING = "In progress"
    RETURNED = "Result returned"
    VERIFIED = "Verified"
    FAILED = "Failed"
    UNCERTAIN = "Needs verification"


@dataclass(frozen=True, slots=True)
class CanvasAction:
    id: Identity
    title: Title
    text: Body
    created_at: Timestamp
    state: ActionState
    work_ids: tuple[Identity, ...]
    tool: str = ""
    kind: Literal["action"] = "action"

    @property
    def origins(self) -> tuple[Origin, ...]:
        return (Origin(App.WORKSPACE, "Workspace"),)


@dataclass(frozen=True, slots=True)
class CanvasUpdate:
    id: Identity
    title: Title
    text: Body
    created_at: Timestamp
    work_ids: tuple[Identity, ...] = ()
    kind: Literal["update"] = "update"

    @property
    def origins(self) -> tuple[Origin, ...]:
        return (Origin(App.WORKSPACE, "Workspace"),)


@dataclass(frozen=True, slots=True)
class CanvasQuestion:
    id: Identity
    title: Title
    text: Body
    created_at: Timestamp
    request: CanvasRequest
    reply: CanvasReply
    work_ids: tuple[Identity, ...] = ()
    kind: Literal["question"] = "question"

    @property
    def origins(self) -> tuple[Origin, ...]:
        return (Origin(App.WORKSPACE, "Workspace"),)


type CanvasActivity = Annotated[CanvasUpdate | CanvasQuestion | CanvasAction, Field(discriminator="kind")]


def task_activity(tasks: tuple[contracts.task.Task, ...], runs: tuple[CanvasRun, ...]) -> tuple[CanvasActivity, ...]:
    result: tuple[CanvasActivity, ...] = ()
    for task in tasks:
        work_ids = tuple(run.work_id for run in runs if run.task_id == task.id and run.work_id != ROOT_CONTEXT)
        match task.state:
            case contracts.task.Waiting(contracts.task.Question(id=identity, text=title, detail=detail)):
                result = (
                    *result,
                    CanvasQuestion(
                        "question:" + identity,
                        title[:240],
                        question_body(title, detail),
                        task.updated_at,
                        TaskRequest(task.id, identity),
                        Attention.WAITING,
                        work_ids,
                    ),
                )
            case contracts.task.Completed(result=text) if work_ids and any(
                run.task_id == task.id and isinstance(run.intent, CanvasResearch) for run in runs
            ):
                result = (*result, CanvasUpdate("result:" + task.id, task.title[:240], text[:32000], task.updated_at, work_ids))
            case _:
                pass
    return result


def settle_tasks(
    activity: tuple[CanvasActivity, ...], tasks: tuple[contracts.task.Task, ...], rejected: frozenset[TaskRequest]
) -> tuple[CanvasActivity, ...]:
    live = frozenset(item.request for item in task_activity(tasks, ()) if isinstance(item, CanvasQuestion))

    def settle(item: CanvasActivity) -> CanvasActivity:
        match item:
            case CanvasQuestion(request=TaskRequest() as request, reply=reply):
                if request in live and request in rejected:
                    return replace(item, reply=Attention.WAITING)
                if request not in live and reply is Attention.WAITING:
                    return replace(item, reply=Attention.CLOSED)
                return item
            case _:
                return item

    return tuple(settle(item) for item in activity)


def merge_activity(previous: CanvasActivity, current: CanvasActivity) -> CanvasActivity:
    work_ids = tuple(frozendict((identity, None) for identity in (*previous.work_ids, *current.work_ids)))
    match previous, current:
        case CanvasQuestion() as old, CanvasQuestion() as new:
            # Accepted context and durable routing survive stale conversation mirrors.
            request = old.request if isinstance(old.request, TaskRequest) else new.request
            reply: CanvasReply
            match old.request, new.request, old.reply, new.reply:
                case _, _, contracts.task.TextAnswer(), _:
                    reply = old.reply
                case TaskRequest(), SessionRequest(), _, Attention.CLOSED:
                    reply = old.reply
                case _:
                    reply = new.reply
            content = old if isinstance(old.request, TaskRequest) and isinstance(new.request, SessionRequest) else new
            return replace(content, request=request, work_ids=work_ids, reply=reply)
        case _, _:
            return replace(current, work_ids=work_ids)


def important_changes(previous: Catalog, current: Catalog) -> tuple[str, ...]:
    known = frozendict((work.id, work) for work in previous.works)
    return tuple(work.id for work in current.works if work.id in known and work.definition.state != known[work.id].definition.state)
