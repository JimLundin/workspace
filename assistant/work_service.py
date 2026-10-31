"""Journal and volatile transport effects, owned by the frontend's observer."""

from collections.abc import Callable
from dataclasses import dataclass, replace
from itertools import islice
from typing import Protocol, assert_never

from assistant.work_window import (
    AddPreference,
    AddProjectNote,
    AnswerTask,
    ControlTask,
    CreateRoutine,
    DisableRoutine,
    EnableRoutine,
    FollowUp,
    Redirect,
    RefreshApproval,
    RemoveContext,
    ReplyProblem,
    SubmissionProblem,
    Submit,
    UpdatePreference,
    UpdateProjectNote,
    UpdateRoutine,
    WorkCommand,
    WorkSnapshot,
)
from automation.activity import ContextSnapshot
from automation.context import ContextStore, Preference, ProjectNote
from automation.execution import ApprovalReview, review_matches
from automation.ipc import (
    Envelope,
    LogEvent,
    MeetingFailed,
    MeetingRequest,
    MeetingSucceeded,
    Resync,
    ReviewEvent,
)
from automation.personal_work import AddDocument, AddWebPage, DismissWork, OpenWorkSource, RefreshPersonalWork, RestoreWork, SaveWork, UnlinkWork
from automation.routines import RoutineStore
from automation.store import TaskStore
from automation.task import (
    Approval,
    ApprovalDecision,
    Completed,
    Control,
    Profile,
    Question,
    RequestSource,
    RoutineSource,
    Running,
    Task,
    Waiting,
    owns,
    text,
)


class WorkBridge(Protocol):
    """The UI process uses bounded, authenticated, non-persistent exchanges."""

    def connect(self) -> str: ...
    def poll(self, limit: int = 64) -> tuple[Envelope, ...]: ...
    def wake(self) -> None: ...
    def register(self, task_id: str, context: ContextSnapshot | None, *, assistant_pid: int) -> None: ...
    def publish_context(self, context: ContextSnapshot, *, assistant_pid: int) -> None: ...
    def respond(self, message: Envelope, result: MeetingSucceeded | MeetingFailed) -> bool: ...
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


type TaskCommand = Submit | FollowUp | Redirect | ControlTask | AnswerTask | RefreshApproval
type RoutineCommand = CreateRoutine | UpdateRoutine | EnableRoutine | DisableRoutine
type ContextCommand = AddPreference | UpdatePreference | AddProjectNote | UpdateProjectNote | RemoveContext


def submission_matches(task: Task, submission: UnconfirmedSubmission) -> bool:
    """The caller resolved this task by ID; verify its remaining submission constraints."""
    match task.source:
        case RequestSource(conversation_id, profile):
            conversation = submission.conversation_id is None or conversation_id == submission.conversation_id
            return task.prompt == submission.prompt and profile == submission.profile and conversation
        case RoutineSource():
            return False
        case _:
            assert_never(task.source)


def follow_up_prompt(task: Task, prompt: str) -> str:
    """Keep the referenced outcome useful even after volatile history is lost."""
    text(prompt, "follow-up request")
    previous = task.state.result if isinstance(task.state, Completed) else task.checkpoint.summary if task.checkpoint else task.prompt
    return text(f"Follow-up to {task.title} (task {task.id}).\nPrevious work:\n{previous[:8_000]}\n\nNew request:\n{prompt}", "task prompt")


class WorkService:
    __slots__ = (
        "_epoch",
        "_pending_inputs",
        "_replies",
        "_reviews",
        "_sequence",
        "_submissions",
        "assistant_pid",
        "bridge",
        "connection_status",
        "context",
        "problem",
        "routines",
        "tasks",
    )

    def __init__(
        self,
        tasks: TaskStore,
        routines: RoutineStore,
        context: ContextStore,
        bridge: WorkBridge,
        *,
        assistant_pid: int,
    ) -> None:
        self.tasks, self.routines, self.context, self.bridge = tasks, routines, context, bridge
        self.assistant_pid = assistant_pid
        self._epoch: str | None = None
        self._sequence = 0
        self._reviews: dict[str, ReviewEvent] = {}
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
        self._reviews.clear()
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
                match existing.source:
                    case RequestSource(profile=profile) as original if profile == source.profile and existing.prompt == request.prompt.strip():
                        source = original
                    case _:
                        raise ValueError("That task identity already belongs to a different request.")
            issued = Issued(Submit(request.prompt), request.identity, source, request.context)
        else:
            issued = request
        command = issued.command
        match command:
            case Submit() | FollowUp() | Redirect() | ControlTask() | AnswerTask() | RefreshApproval():
                self._task_command(issued, command, at=at)
            case CreateRoutine() | UpdateRoutine() | EnableRoutine() | DisableRoutine():
                self._routine_command(issued.identity, command, at=at)
            case AddPreference() | UpdatePreference() | AddProjectNote() | UpdateProjectNote() | RemoveContext():
                self._context_command(issued.identity, command, at=at)
            case AddDocument() | AddWebPage() | DismissWork() | RestoreWork() | SaveWork() | UnlinkWork() | OpenWorkSource() | RefreshPersonalWork():
                raise ValueError("Personal work commands belong to the My work owner.")
            case _:
                assert_never(command)
        self.problem = ""
        self._transport(self.bridge.wake)

    def _task_command(self, issued: Issued, command: TaskCommand, *, at: float) -> None:
        match command:
            case Submit(prompt):
                self._submit(issued.identity, prompt, issued.source, issued.context, at=at)
            case FollowUp(task_id, prompt):
                original = self.tasks.get(task_id)
                if original is None:
                    raise ValueError("The task for this follow-up no longer exists.")
                # A follow-up is the person's own request in the original conversation, whatever the original's profile.
                source = issued.source if not isinstance(original.source, RequestSource) else RequestSource(original.source.conversation_id)
                self._submit(issued.identity, follow_up_prompt(original, prompt), source, issued.context, at=at)
            case Redirect(task_id, prompt):
                original = self.tasks.get(task_id)
                if original is None:
                    raise ValueError("The task to redirect no longer exists.")
                self.register(task_id, issued.context)
                if self.tasks.revise(task_id, prompt, at=at) is None:
                    raise ValueError("The task to redirect no longer exists.")
                self._reviews.pop(task_id, None)
            case ControlTask(task_id, control):
                if self.tasks.control(task_id, control, at=at) is None:
                    raise ValueError("That task control is no longer available.")
                self._reviews.pop(task_id, None)
            case AnswerTask(task_id, request_id, answer):
                if answer is ApprovalDecision.APPROVED:
                    # A previously painted preview becomes invalid as soon as
                    # the worker epoch changes, even before the next UI poll.
                    try:
                        if self.bridge.connect() != self._epoch:
                            self._disconnected()
                    except OSError, ValueError:
                        self._disconnected()
                task = self.tasks.get(task_id)
                review = self._reviews.get(task_id)
                if answer is ApprovalDecision.APPROVED and (task is None or review is None or not review_matches(task, review.review)):
                    raise ValueError("Request a fresh preview before approving this operation.")
                if self.tasks.answer(task_id, request_id, answer, at=at) is None:
                    raise ValueError("This question or approval is no longer waiting for that reply.")
                self._replies.pop((task_id, request_id), None)
                self._reviews.pop(task_id, None)
            case RefreshApproval(task_id, request_id):
                if self.tasks.refresh_approval(task_id, request_id, at=at) is None:
                    raise ValueError("That approval has changed. Read its current request before refreshing.")
                self._reviews.pop(task_id, None)
            case _:
                assert_never(command)

    def _routine_command(self, identity: str, command: RoutineCommand, *, at: float) -> None:
        match command:
            case CreateRoutine(title, instruction, trigger):
                self.routines.create(identity, title, instruction, trigger, at=at)
            case UpdateRoutine(identity, revision, title, instruction, trigger):
                self.routines.update(identity, title, instruction, trigger, at=at, expected_revision=revision)
            case EnableRoutine(identity):
                self.routines.enable(identity, at=at)
            case DisableRoutine(identity):
                self.routines.disable(identity, at=at)
            case _:
                assert_never(command)

    def _context_command(self, identity: str, command: ContextCommand, *, at: float) -> None:
        match command:
            case AddPreference(name, value, source):
                self.context.save(Preference(identity, name, value, source, at))
            case UpdatePreference(identity, name, value, source):
                if not isinstance(self.context.get(identity), Preference):
                    raise ValueError("The preference being edited no longer exists.")
                self.context.save(Preference(identity, name, value, source, at))
            case AddProjectNote(project, content, source, valid_for):
                self.context.save(ProjectNote(identity, project, content, source, at, at + valid_for))
            case UpdateProjectNote(identity, project, content, source, valid_for):
                if not isinstance(self.context.get(identity), ProjectNote):
                    raise ValueError("The project note being edited no longer exists.")
                self.context.save(ProjectNote(identity, project, content, source, at, at + valid_for))
            case RemoveContext(identity):
                self.context.remove(identity)
            case _:
                assert_never(command)

    def stop_conversation(self, conversation_id: str, *, at: float) -> None:
        self.tasks.control_conversation(conversation_id, Control.CANCEL, at=at)
        self._transport(self.bridge.wake)

    def events(self, *, at: float) -> tuple[Envelope, ...]:
        try:
            epoch = self.bridge.connect()
            if epoch != self._epoch:
                self._epoch, self._sequence = epoch, 0
                self._reviews.clear()
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
                    self._reviews.clear()
                case ReviewEvent(run, review):
                    task = self.tasks.get(run.task_id)
                    if (
                        task is not None
                        and task.id == review.task_id
                        and task.goal_revision == review.goal_revision
                        and (owns(task, run) or (review_matches(task, review) and self.tasks.request_run(task.id, review.request.id) == run))
                    ):
                        if len(self._reviews) >= 1_000:
                            self._reviews.pop(next(iter(self._reviews)))
                        self._reviews[task.id] = message.payload
                case LogEvent() | MeetingRequest():
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
        self._reviews.clear()
        self._limit_submissions(watched)
        self._limit_replies(watched)
        current = {task.id: task for task in previous.tasks}
        return replace(
            previous,
            status=self.problem or "The work journal is unavailable.",
            reviews=(),
            submission_problems=self._submission_problems(current, watched, pending, confirmed=False),
            reply_problems=(),
        )

    def _confirmed_reply_problems(self, current: dict[str, Task], watched: frozenset[str]) -> tuple[ReplyProblem, ...]:
        self._pending_inputs = frozenset(
            (task.id, task.state.reason.id)
            for task in current.values()
            if isinstance(task.state, Waiting) and isinstance(task.state.reason, (Question, Approval))
        )
        for key in tuple(self._replies):
            if (key[0] in current or key[0] in watched) and key not in self._pending_inputs:
                self._replies.pop(key)
        self._limit_replies(watched)
        return tuple(problem for key, problem in self._replies.items() if key in self._pending_inputs)

    def snapshot(self, *, at: float, watched: frozenset[str] = frozenset(), pending: frozenset[str] = frozenset()) -> WorkSnapshot:
        self._limit_submissions(watched)
        tasks = self.tasks.list_tasks(limit=1_000)
        current = {task.id: task for task in tasks}
        # Watched rows and unconfirmed writes share one bounded read snapshot.
        for retained in self.tasks.get_many(tuple(sorted(watched | self._submissions.keys()))):
            current[retained.id] = retained
        tasks = tuple(current.values())
        reviews: list[ApprovalReview] = []
        for identity, event in tuple(self._reviews.items()):
            task = current.get(identity)
            if task is not None and review_matches(task, event.review):
                reviews.append(event.review)
            elif task is None or not isinstance(task.state, Running) or not owns(task, event.run) or task.goal_revision != event.review.goal_revision:
                self._reviews.pop(identity)
        routines, context = self.routines.summaries(at), self.context.list()
        problems = self._submission_problems(current, watched, pending, confirmed=True)
        reply_problems = self._confirmed_reply_problems(current, watched)
        # Only watched tasks need an action timeline. Bound journal reads and
        # publication size; the task journal retains the complete ledger.
        actions = tuple(islice((action for task in tasks if task.id in watched for action in self.tasks.actions(task.id, limit=16)), 256))
        return WorkSnapshot(
            tasks, routines, context, self.problem or self.connection_status, tuple(reviews), problems, reply_problems, actions=actions
        )
