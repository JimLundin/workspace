"""Journal effects and worker notifications, owned by the frontend's observer."""

from dataclasses import dataclass, replace
from itertools import islice
from typing import Protocol, assert_never

from automation.activity import ContextSnapshot
from automation.context import ContextStore
from automation.store import TaskStore
from contracts.task import (
    Control,
    Profile,
    Question,
    RequestSource,
    Task,
    Waiting,
    text,
)
from contracts.work_commands import AnswerTask, ControlTask, Submit, WorkCommand
from contracts.work_snapshot import ReplyProblem, SubmissionProblem, WorkSnapshot


class Worker(Protocol):
    """The in-process worker: it reads each request's context and wakes after commits."""

    def register(self, task_id: str, context: ContextSnapshot | None) -> None: ...
    def wake(self) -> None: ...


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
    __slots__ = ("_pending_inputs", "_replies", "_submissions", "context", "problem", "tasks", "worker")

    def __init__(self, tasks: TaskStore, context: ContextStore, worker: Worker) -> None:
        self.tasks, self.context, self.worker = tasks, context, worker
        self._submissions: dict[str, UnconfirmedSubmission] = {}
        self._replies: dict[tuple[str, str], ReplyProblem] = {}
        self._pending_inputs: frozenset[tuple[str, str]] = frozenset()
        self.problem = ""

    def _submit(self, identity: str, prompt: str, source: RequestSource, context: ContextSnapshot | None, *, at: float) -> Task:
        prompt = text(prompt, "task prompt").strip()
        existing = self.tasks.get(identity)
        if existing is not None:
            if existing.source != source or existing.prompt != prompt:
                raise ValueError("That task identity already belongs to a different request.")
            self._submissions.pop(identity, None)
            return existing
        # Registration precedes eligibility in SQLite, so the worker's claim finds it.
        self.worker.register(identity, context)
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
        """Commit a user command before waking the worker."""
        if isinstance(request, IdentifiedSubmission):
            existing = self.tasks.get(request.identity)
            source = request.source
            if existing is not None:
                if existing.source.profile != source.profile or existing.prompt != request.prompt.strip():
                    raise ValueError(f"That task identity already belongs to a different request: {request.identity}.")
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
        self.worker.wake()

    def stop_conversation(self, conversation_id: str, *, at: float) -> None:
        self.tasks.control_conversation(conversation_id, Control.CANCEL, at=at)
        self.worker.wake()

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
        return WorkSnapshot(tasks, context, self.problem, submission_problems=problems, reply_problems=reply_problems, actions=actions)
