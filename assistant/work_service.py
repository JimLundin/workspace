"""Journal and volatile transport effects, owned by the frontend's observer."""

from collections.abc import Callable
from dataclasses import dataclass, replace
from itertools import islice
from typing import Protocol, assert_never

from assistant.work_commands import AnswerTask, ControlTask, Submit, WorkCommand
from assistant.work_snapshot import ReplyProblem, SubmissionProblem, WorkSnapshot
from automation import ipc
from automation.activity import ContextSnapshot
from automation.context import ContextStore
from automation.ipc import (
    Envelope,
    LogEvent,
    OwnerRequest,
    Resync,
)
from automation.store import TaskStore
from automation.task import (
    Control,
    Profile,
    Question,
    RequestSource,
    Task,
    Waiting,
    text,
)


class WorkBridge(Protocol):
    """The UI process uses bounded, authenticated, non-persistent exchanges."""

    def connect(self) -> str: ...
    def poll(self, limit: int = 64) -> tuple[Envelope, ...]: ...
    def wake(self) -> None: ...
    def register(self, task_id: str, context: ContextSnapshot | None, *, assistant_pid: int) -> None: ...
    def publish_context(self, context: ContextSnapshot, *, assistant_pid: int) -> None: ...
    def respond(self, message: Envelope, result: ipc.Succeeded | ipc.Failed) -> bool: ...
    def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class Issued:
    command: WorkCommand
    identity: str
    source: RequestSource
    context: ContextSnapshot | None


@dataclass(frozen=True, slots=True)
class IdentifiedSubmission:
    identity: str
    prompt: str
    source: RequestSource
    context: ContextSnapshot | None


type WorkRequest = Issued | IdentifiedSubmission


@dataclass(frozen=True, slots=True)
class UnconfirmedSubmission:
    prompt: str
    profile: Profile
    conversation_id: str | None
    """An identified submission reuses its task from any conversation."""
    problem: SubmissionProblem


def submission_matches(task: Task, submission: UnconfirmedSubmission) -> bool:
    """The caller resolved this task by ID; verify its remaining submission constraints."""
    conversation = submission.conversation_id is None or task.source.conversation_id == submission.conversation_id
    return task.prompt == submission.prompt and task.source.profile == submission.profile and conversation


class WorkService:
    __slots__ = (
        "_epoch",
        "_pending_inputs",
        "_replies",
        "_sequence",
        "_submissions",
        "assistant_pid",
        "bridge",
        "connection_status",
        "context",
        "problem",
        "tasks",
    )

    def __init__(
        self,
        tasks: TaskStore,
        context: ContextStore,
        bridge: WorkBridge,
        *,
        assistant_pid: int,
    ) -> None:
        self.tasks, self.context, self.bridge = tasks, context, bridge
        self.assistant_pid = assistant_pid
        self._epoch: str | None = None
        self._sequence = 0
        self._submissions: dict[str, UnconfirmedSubmission] = {}
        self._replies: dict[tuple[str, str], ReplyProblem] = {}
        self._pending_inputs: frozenset[tuple[str, str]] = frozenset()
        self.problem = self.connection_status = ""

    def _transport(self, operation: Callable[[], None]) -> None:
        try:
            operation()
        except OSError, ValueError:
            self._disconnected()

    def _disconnected(self) -> None:
        self._epoch = None
        self.connection_status = "Work is saved. Waiting for the work process to reconnect."

    def register(self, identity: str, context: ContextSnapshot | None) -> None:
        # BridgeClient retains registration before attempting I/O. Registration
        # precedes eligibility in SQLite, so an online worker can claim safely.
        self._transport(lambda: self.bridge.register(identity, context, assistant_pid=self.assistant_pid))

    def publish_context(self, context: ContextSnapshot) -> None:
        self._transport(lambda: self.bridge.publish_context(context, assistant_pid=self.assistant_pid))

    def _submit(self, identity: str, prompt: str, source: RequestSource, context: ContextSnapshot | None, *, at: float) -> Task:
        prompt = text(prompt, "task prompt").strip()
        existing = self.tasks.get(identity)
        if existing is not None:
            if existing.source != source or existing.prompt != prompt:
                raise ValueError("That task identity already belongs to a different request.")
            self._submissions.pop(identity, None)
            return existing
        self.register(identity, context)
        task = self.tasks.submit(identity, prompt.splitlines()[0][:240], prompt, source, at=at)
        if task.source != source or task.prompt != prompt:
            raise ValueError("That task identity already belongs to a different request.")
        self._submissions.pop(identity, None)
        return task

    def _limit_submissions(self, watched: frozenset[str]) -> None:
        # Keep watched submission failures plus a bounded recent history.
        unwatched = tuple(identity for identity in self._submissions if identity not in watched)
        for identity in unwatched[: max(0, len(unwatched) - 256)]:
            self._submissions.pop(identity)

    def submission_failed(self, issued: WorkRequest, reason: str, *, watched: frozenset[str]) -> None:
        conversation: str | None
        match issued:
            case Issued(command=Submit(prompt), source=RequestSource(conversation)):
                pass
            case IdentifiedSubmission(prompt=prompt):
                conversation = None
            case Issued():
                return
            case _:
                assert_never(issued)
        problem = SubmissionProblem(issued.identity, f"Could not confirm this submission: {reason[:4_000]}".replace("\0", "�"))
        self._submissions.pop(issued.identity, None)
        self._submissions[issued.identity] = UnconfirmedSubmission(prompt.strip(), issued.source.profile, conversation, problem)
        self._limit_submissions(watched)

    def _limit_replies(self, watched: frozenset[str]) -> None:
        recent = tuple(key for key in self._replies if key[0] not in watched or key not in self._pending_inputs)
        for key in recent[: max(0, len(recent) - 256)]:
            self._replies.pop(key)

    def reply_failed(self, issued: Issued, reason: str, *, watched: frozenset[str]) -> None:
        if not isinstance(issued.command, AnswerTask):
            return
        command = issued.command
        key = command.task_id, command.request_id
        problem = ReplyProblem(
            task_id=command.task_id,
            request_id=command.request_id,
            receipt_id=issued.identity,
            reason=f"This reply was not saved: {reason[:4_000]}".replace("\0", "�"),
        )
        self._replies.pop(key, None)
        self._replies[key] = problem
        self._limit_replies(watched)

    def apply(self, request: WorkRequest, *, at: float) -> None:
        """Commit a user command before notifying the work process."""
        if isinstance(request, IdentifiedSubmission):
            existing = self.tasks.get(request.identity)
            source = request.source
            if existing is not None:
                if existing.source.profile != source.profile or existing.prompt != request.prompt.strip():
                    raise ValueError("That task identity already belongs to a different request.")
                source = existing.source
            issued = Issued(Submit(request.prompt), request.identity, source, request.context)
        else:
            issued = request
        match issued.command:
            case Submit(prompt):
                self._submit(issued.identity, prompt, issued.source, issued.context, at=at)
            case ControlTask(task_id, control):
                if self.tasks.control(task_id, control, at=at) is None:
                    raise ValueError("That task control is no longer available.")
            case AnswerTask(task_id, request_id, answer):
                if self.tasks.answer(task_id, request_id, answer, at=at) is None:
                    raise ValueError("This question is no longer waiting for that reply.")
                self._replies.pop((task_id, request_id), None)
            case _:
                assert_never(issued.command)
        self.problem = ""
        self._transport(self.bridge.wake)

    def stop_conversation(self, conversation_id: str, *, at: float) -> None:
        self.tasks.control_conversation(conversation_id, Control.CANCEL, at=at)
        self._transport(self.bridge.wake)

    def events(self, *, at: float) -> tuple[Envelope, ...]:
        try:
            epoch = self.bridge.connect()
            if epoch != self._epoch:
                self._epoch, self._sequence = epoch, 0
            messages = self.bridge.poll()
        except OSError, ValueError:
            self._disconnected()
            return ()
        self.connection_status = ""
        accepted: list[Envelope] = []
        for message in messages:
            if message.epoch != self._epoch or message.sequence <= self._sequence:
                continue
            self._sequence = message.sequence
            match message.payload:
                case Resync():
                    pass
                case LogEvent() | OwnerRequest():
                    accepted.append(message)
                case _:
                    assert_never(message.payload)
        return tuple(accepted)

    def _submission_problems(
        self,
        current: dict[str, Task],
        watched: frozenset[str],
        pending: frozenset[str],
        *,
        confirmed: bool,
    ) -> tuple[SubmissionProblem, ...]:
        for identity, submission in tuple(self._submissions.items()):
            task = current.get(identity)
            if confirmed and task is not None and submission_matches(task, submission):
                self._submissions.pop(identity)
        problems = {identity: submission.problem for identity, submission in self._submissions.items()}
        missing_reason = (
            "No saved task was found for this request. Submit it again if you want to retry."
            if confirmed
            else "Could not confirm this request while the work journal is unavailable."
        )
        for identity in sorted(watched - current.keys() - pending):
            if identity not in problems:
                problems[identity] = SubmissionProblem(identity, missing_reason)
        return tuple(problems.values())

    def unavailable(self, previous: WorkSnapshot, watched: frozenset[str], pending: frozenset[str]) -> WorkSnapshot:
        """Keep known state; failed reads cannot prove that a commit did not happen."""
        self._limit_submissions(watched)
        self._limit_replies(watched)
        current = {task.id: task for task in previous.tasks}
        return replace(
            previous,
            status=self.problem or "The work journal is unavailable.",
            submission_problems=self._submission_problems(current, watched, pending, confirmed=False),
            reply_problems=(),
        )

    def _confirmed_reply_problems(self, current: dict[str, Task], watched: frozenset[str]) -> tuple[ReplyProblem, ...]:
        self._pending_inputs = frozenset(
            (task.id, task.state.reason.id)
            for task in current.values()
            if isinstance(task.state, Waiting) and isinstance(task.state.reason, Question)
        )
        for key in tuple(self._replies):
            if (key[0] in current or key[0] in watched) and key not in self._pending_inputs:
                self._replies.pop(key)
        self._limit_replies(watched)
        return tuple(problem for key, problem in self._replies.items() if key in self._pending_inputs)

    def snapshot(self, *, watched: frozenset[str] = frozenset(), pending: frozenset[str] = frozenset()) -> WorkSnapshot:
        self._limit_submissions(watched)
        tasks = self.tasks.list_tasks(limit=1_000)
        current = {task.id: task for task in tasks}
        # Watched rows and unconfirmed writes share one bounded read snapshot.
        for retained in self.tasks.get_many(tuple(sorted(watched | self._submissions.keys()))):
            current[retained.id] = retained
        tasks = tuple(current.values())
        context = self.context.list()
        problems = self._submission_problems(current, watched, pending, confirmed=True)
        reply_problems = self._confirmed_reply_problems(current, watched)
        # Only watched tasks need an action timeline. Bound journal reads and
        # publication size; the task journal retains the complete ledger.
        actions = tuple(islice((action for task in tasks if task.id in watched for action in self.tasks.actions(task.id, limit=16)), 256))
        return WorkSnapshot(
            tasks, context, self.problem or self.connection_status, submission_problems=problems, reply_problems=reply_problems, actions=actions
        )
