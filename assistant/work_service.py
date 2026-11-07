"""Journal effects and worker notifications, owned by the frontend's observer."""

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field, replace
from itertools import chain, islice
from typing import Protocol, assert_never

from automation.activity import ContextSnapshot
from automation.context import ContextStore
from automation.store import TaskStore
from cell import Cell
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


def _set[K, V](mapping: frozendict[K, V], key: K, value: V) -> frozendict[K, V]:
    """`mapping` with `key` moved last and holding `value`."""
    return frozendict((*((name, held) for name, held in mapping.items() if name != key), (key, value)))


def _without[K, V](mapping: frozendict[K, V], dropped: Collection[K]) -> frozendict[K, V]:
    return frozendict((key, value) for key, value in mapping.items() if key not in dropped)


def _oldest_beyond[K](keys: Sequence[K], limit: int) -> frozenset[K]:
    """The oldest of `keys` that exceed `limit`."""
    return frozenset(keys[: max(0, len(keys) - limit)])


@dataclass(frozen=True, slots=True)
class _Pending:
    submissions: frozendict[str, UnconfirmedSubmission] = frozendict()
    """Submissions not yet confirmed in the journal, oldest first."""
    replies: frozendict[tuple[str, str], ReplyProblem] = frozendict()
    """Replies that failed to save, by task and request, oldest first."""
    pending_inputs: frozenset[tuple[str, str]] = frozenset()
    """Questions the journal last showed waiting."""
    problem: str = ""
    """Why the last request or refresh failed."""


@dataclass(frozen=True, slots=True)
class WorkService:
    tasks: TaskStore
    context: ContextStore
    worker: Worker
    _state: Cell[_Pending] = field(default_factory=lambda: Cell(_Pending()), init=False, repr=False)

    @property
    def problem(self) -> str:
        return self._state.get().problem

    def failed(self, problem: str) -> None:
        """Report why a request or refresh failed, until the next request succeeds."""
        self._state.update(lambda state: replace(state, problem=problem))

    def _confirmed(self, identity: str) -> None:
        self._state.update(lambda state: replace(state, submissions=_without(state.submissions, (identity,))))

    def _submit(self, identity: str, prompt: str, source: RequestSource, context: ContextSnapshot | None, *, at: float) -> Task:
        prompt = text(prompt, "task prompt").strip()
        existing = self.tasks.get(identity)
        if existing is not None:
            if existing.source != source or existing.prompt != prompt:
                raise ValueError("That task identity already belongs to a different request.")
            self._confirmed(identity)
            return existing
        # Registration precedes eligibility in SQLite, so the worker's claim finds it.
        self.worker.register(identity, context)
        task = self.tasks.submit(identity, prompt.splitlines()[0][:240], prompt, source, at=at)
        if task.source != source or task.prompt != prompt:
            raise ValueError("That task identity already belongs to a different request.")
        self._confirmed(identity)
        return task

    def _limit_submissions(self, watched: frozenset[str]) -> None:
        # Keep watched submission failures plus a bounded recent history.
        def limited(state: _Pending) -> _Pending:
            unwatched = tuple(identity for identity in state.submissions if identity not in watched)
            return replace(state, submissions=_without(state.submissions, _oldest_beyond(unwatched, 256)))

        self._state.update(limited)

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
        problem = SubmissionProblem(issued.identity, f"Could not confirm this submission: {reason[:4_000]}".replace("\0", "\ufffd"))
        submission = UnconfirmedSubmission(prompt.strip(), issued.source.profile, conversation, problem)
        self._state.update(lambda state: replace(state, submissions=_set(state.submissions, issued.identity, submission)))
        self._limit_submissions(watched)

    def _limit_replies(self, watched: frozenset[str]) -> None:
        def limited(state: _Pending) -> _Pending:
            recent = tuple(key for key in state.replies if key[0] not in watched or key not in state.pending_inputs)
            return replace(state, replies=_without(state.replies, _oldest_beyond(recent, 256)))

        self._state.update(limited)

    def reply_failed(self, issued: Issued, reason: str, *, watched: frozenset[str]) -> None:
        if not isinstance(issued.command, AnswerTask):
            return
        command = issued.command
        key = command.task_id, command.request_id
        problem = ReplyProblem(
            task_id=command.task_id,
            request_id=command.request_id,
            receipt_id=issued.identity,
            reason=f"This reply was not saved: {reason[:4_000]}".replace("\0", "\ufffd"),
        )
        self._state.update(lambda state: replace(state, replies=_set(state.replies, key, problem)))
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
                self._state.update(lambda state: replace(state, replies=_without(state.replies, ((task_id, request_id),))))
            case _:
                assert_never(issued.command)
        self._state.update(lambda state: replace(state, problem=""))
        self.worker.wake()

    def stop_conversation(self, conversation_id: str, *, at: float) -> None:
        self.tasks.control_conversation(conversation_id, Control.CANCEL, at=at)
        self.worker.wake()

    def _submission_problems(
        self,
        current: Mapping[str, Task],
        watched: frozenset[str],
        pending: frozenset[str],
        *,
        confirmed: bool,
    ) -> tuple[SubmissionProblem, ...]:
        def matched(state: _Pending) -> _Pending:
            done = frozenset(
                identity
                for identity, submission in state.submissions.items()
                if confirmed and (task := current.get(identity)) is not None and submission_matches(task, submission)
            )
            return replace(state, submissions=_without(state.submissions, done))

        submissions = self._state.update(matched).submissions
        problems = {identity: submission.problem for identity, submission in submissions.items()}
        missing_reason = (
            "No saved task was found for this request. Submit it again if you want to retry."
            if confirmed
            else "Could not confirm this request while the work journal is unavailable."
        )
        missing = (SubmissionProblem(identity, missing_reason) for identity in sorted(watched - current.keys() - pending) if identity not in problems)
        return (*problems.values(), *missing)

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

    def _confirmed_reply_problems(self, current: Mapping[str, Task], watched: frozenset[str]) -> tuple[ReplyProblem, ...]:
        waiting = frozenset(
            (task.id, task.state.reason.id)
            for task in current.values()
            if isinstance(task.state, Waiting) and isinstance(task.state.reason, Question)
        )
        answered = frozenset(key for key in self._state.get().replies if (key[0] in current or key[0] in watched) and key not in waiting)
        self._state.update(lambda state: replace(state, pending_inputs=waiting, replies=_without(state.replies, answered)))
        self._limit_replies(watched)
        state = self._state.get()
        return tuple(problem for key, problem in state.replies.items() if key in state.pending_inputs)

    def snapshot(self, *, watched: frozenset[str] = frozenset(), pending: frozenset[str] = frozenset()) -> WorkSnapshot:
        self._limit_submissions(watched)
        tasks = self.tasks.list_tasks(limit=1_000)
        # Watched rows and unconfirmed writes share one bounded read snapshot.
        retained = self.tasks.get_many(tuple(sorted(watched | self._state.get().submissions.keys())))
        current = {task.id: task for task in chain(tasks, retained)}
        tasks = tuple(current.values())
        context = self.context.list()
        problems = self._submission_problems(current, watched, pending, confirmed=True)
        reply_problems = self._confirmed_reply_problems(current, watched)
        # Only watched tasks need an action timeline. Bound journal reads and
        # publication size; the task journal retains the complete ledger.
        actions = tuple(islice((action for task in tasks if task.id in watched for action in self.tasks.actions(task.id, limit=16)), 256))
        return WorkSnapshot(tasks, context, self.problem, submission_problems=problems, reply_problems=reply_problems, actions=actions)
