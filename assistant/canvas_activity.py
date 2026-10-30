"""Agent-owned canvas activity, exact clarification routing and quiet redirects.

App observations remain context for the agent. Clarifications and material work
changes are the interaction surface; ordinary app arrivals do not become alerts.
"""

from dataclasses import dataclass, replace
from enum import Enum
from typing import Annotated, Literal, assert_never

from pydantic import Field

import assistant.agent_session
import automation.task
from assistant.communications import Feed
from assistant.feed_origin import App, FeedRequest, Origin
from assistant.feed_triage import Board
from automation.personal_work import Catalog, Identity, Title

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


type CanvasReply = Attention | assistant.agent_session.Answered


def canvas_reply(reply: assistant.agent_session.Reply) -> CanvasReply:
    match reply:
        case assistant.agent_session.Pending():
            return Attention.WAITING
        case assistant.agent_session.Cancelled() | automation.task.ApprovalDecision():
            return Attention.CLOSED
        case assistant.agent_session.Answered():
            return reply
        case _:
            assert_never(reply)


@dataclass(frozen=True, slots=True)
class CanvasResearch:
    evidence: str | None = None
    kind: Literal["research"] = "research"


@dataclass(frozen=True, slots=True)
class CanvasInstruction:
    text: Body
    kind: Literal["instruction"] = "instruction"

    def __post_init__(self) -> None:
        automation.task.text(self.text, "canvas instruction", maximum=32000)


type CanvasIntent = Annotated[CanvasResearch | CanvasInstruction, Field(discriminator="kind")]


@dataclass(frozen=True, slots=True)
class CanvasRun:
    task_id: Identity
    work_id: Identity
    intent: CanvasIntent = CanvasResearch()

    @property
    def evidence(self) -> str | None:
        match self.intent:
            case CanvasResearch(evidence=evidence):
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


def session_activity(session: assistant.agent_session.Snapshot) -> tuple[CanvasActivity, ...]:
    result: tuple[CanvasActivity, ...] = ()
    work_ids: tuple[str, ...] = ()
    for message in session.messages:
        match message:
            case assistant.agent_session.ChatMessage(speaker="You", source=source):
                work_ids = (source.identity,) if source is not None else ()
            case assistant.agent_session.AgentRequest(
                request=automation.task.Question(id=identity, text=title), detail=detail, created_at=at, reply=reply
            ):
                result = (
                    *result,
                    CanvasQuestion(
                        "question:" + identity,
                        title[:240] or "Your input is needed",
                        question_body(title, detail),
                        at,
                        SessionRequest(session.identity, identity),
                        canvas_reply(reply),
                        work_ids,
                    ),
                )
            case _:
                pass
    return result


def task_activity(tasks: tuple[automation.task.Task, ...], runs: tuple[CanvasRun, ...]) -> tuple[CanvasActivity, ...]:
    result: tuple[CanvasActivity, ...] = ()
    for task in tasks:
        work_ids = tuple(run.work_id for run in runs if run.task_id == task.id and run.work_id != ROOT_CONTEXT)
        match task.state:
            case automation.task.Waiting(automation.task.Question(id=identity, text=title, detail=detail)):
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
            case automation.task.Completed(result=text) if work_ids and any(
                run.task_id == task.id and isinstance(run.intent, CanvasResearch) for run in runs
            ):
                result = (*result, CanvasUpdate("result:" + task.id, task.title[:240], text[:32000], task.updated_at, work_ids))
            case _:
                pass
    return result


def connected_work(update: CanvasActivity, catalog: Catalog) -> tuple[str, ...]:
    return tuple(work.id for work in catalog.works if work.id in update.work_ids)


def settle_session(activity: tuple[CanvasActivity, ...], session: assistant.agent_session.Snapshot) -> tuple[CanvasActivity, ...]:
    live = frozenset(item.request for item in session_activity(session) if isinstance(item, CanvasQuestion))
    return tuple(
        replace(item, reply=Attention.CLOSED)
        if isinstance(item, CanvasQuestion)
        and isinstance(item.request, SessionRequest)
        and item.reply is Attention.WAITING
        and item.request not in live
        else item
        for item in activity
    )


def settle_tasks(
    activity: tuple[CanvasActivity, ...], tasks: tuple[automation.task.Task, ...], rejected: frozenset[TaskRequest]
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
                case _, _, assistant.agent_session.Answered(), _:
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


def redirect_session(session: assistant.agent_session.Snapshot) -> assistant.agent_session.Snapshot:
    """The floating surface is navigation and guarded approvals, not app arrivals."""
    messages: tuple[assistant.agent_session.Message, ...] = ()
    for message in session.messages:
        match message:
            case assistant.agent_session.AgentRequest(
                request=automation.task.Question(id=identity, text=title), reply=assistant.agent_session.Pending(), created_at=at
            ):
                target = "question:" + identity
                messages = (
                    *messages,
                    assistant.agent_session.ChatMessage(
                        "Workspace",
                        assistant.agent_session.notice_text("Your input is needed · " + title[:180], target),
                        at,
                        FeedRequest("canvas:" + target, title[:240]),
                    ),
                )
            case assistant.agent_session.AgentRequest(request=automation.task.Approval()):
                messages = (*messages, message)
            case assistant.agent_session.ChatMessage(source=source) if source is not None and source.identity.startswith("canvas:"):
                messages = (*messages, message)
            case _:
                pass
    return replace(session, phase="idle", messages=messages, communications=Feed(), triage=Board(), console_requests=())


def history_session(session: assistant.agent_session.Snapshot) -> assistant.agent_session.Snapshot:
    """Explicit history retains agent work without turning app context into cards."""
    return replace(session, communications=Feed(), triage=Board(), console_requests=())
