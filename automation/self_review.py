"""The agent's review of its own work: when a run deserves one, what it reads, and the lessons it keeps.

Decisions are pure over journal records. `ReviewingRunner` is the one effect
owner: after each run it submits the reviews those decisions call for.
"""

import hashlib
import threading
from collections import Counter
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import Enum
from typing import Final, assert_never

from automation.context import ContextRecord, Preference
from automation.controller import Runner
from automation.execution import Log
from automation.store import TaskStore
from automation.task import (
    Action,
    ActionNotApplied,
    ActionPending,
    ActionReturned,
    ActionUncertain,
    ActionVerified,
    Approval,
    Blocked,
    Claim,
    Completed,
    Failed,
    GoalRevision,
    Outcome,
    Question,
    RequestSource,
    Response,
    SelfReview,
    Task,
    TextAnswer,
    Waiting,
    outcome_kind,
    phase,
)


class Signal(Enum):
    """Evidence in a run that the agent's behavior or code could have done better."""

    FAILED = "the task failed"
    BLOCKED = "the run ended blocked or was stopped"
    UNCERTAIN = "an action's outcome was uncertain"
    NOT_APPLIED = "an action was not applied"
    REDIRECTED = "the user revised the goal"
    ASKED = "the agent had to ask the user"


REVIEW_CONVERSATION: Final = "self-review"
REVIEW_PRIORITY: Final = -10
"""Reviews wait behind the user's own work."""
LESSON_SOURCE: Final = "Workspace agent lesson, task "
"""Marks preferences the agent wrote, so it may retire its own lessons but never the user's."""


def signals(outcome: Outcome, actions: Iterable[Action], revisions: Sequence[GoalRevision], responses: Iterable[Response]) -> tuple[Signal, ...]:
    """What a settled run shows; a run still waiting on the user or the keeper is not settled."""
    found: list[Signal] = []
    match outcome:
        case Failed():
            found.append(Signal.FAILED)
        case Waiting(reason=Blocked()):
            found.append(Signal.BLOCKED)
        case Waiting():
            # Waiting on the user's answer, an approval or the keeper: the run is not settled.
            return ()
        case Completed():
            pass
        case _:
            assert_never(outcome)
    outcomes = tuple(action.outcome for action in actions)
    if any(isinstance(item, ActionUncertain) for item in outcomes):
        found.append(Signal.UNCERTAIN)
    if any(isinstance(item, ActionNotApplied) for item in outcomes):
        found.append(Signal.NOT_APPLIED)
    if len(revisions) > 1:
        found.append(Signal.REDIRECTED)
    if any(isinstance(response.request, Question) for response in responses):
        found.append(Signal.ASKED)
    return tuple(found)


def reviewable(task: Task) -> bool:
    """A review never reviews a review, so reviewing cannot feed itself."""
    return not isinstance(task.source.profile, SelfReview)


@dataclass(frozen=True, slots=True)
class Submission:
    id: str
    title: str
    prompt: str
    source: RequestSource


_METHOD: Final = (
    "Find the root cause of each problem: an instruction you misread, a tool you chose badly, missing knowledge about "
    "this user or their applications, or a defect or gap in Workspace's own code, prompts or tools. Then act on it. "
    "A behavior that a short rule would fix becomes a lesson: call save_lesson with one specific, actionable rule. "
    "Call list_lessons first; update or remove a lesson that is wrong, duplicated or superseded instead of adding another. "
    "A cause in Workspace itself is fixed in its source with the self-change tools: edit, check_changes, then "
    "apply_changes; a verified install is committed to main and pushed. "
    "You are authorized to make and install such changes without asking. Keep each change focused on evidence you found. "
    "Do not redo or continue the reviewed work, do not contact anyone, and do not save a lesson that only restates one task. "
    "When nothing generalizes, change nothing. Finish with what you learned and what you changed."
)


def task_review(task: Task, run_id: str, found: Sequence[Signal]) -> Submission:
    """One review per reviewed run: resubmitting the same run reuses its task."""
    key = hashlib.sha256((task.id + "\0" + run_id).encode("utf-8")).hexdigest()[:32]
    prompt = (
        f"Review your own work on task {task.id} ({task.title}). What happened: {'; '.join(item.value for item in found)}. "
        f"Read it with work_history (task_id {task.id}), including its action records, goal revisions and answers. " + _METHOD
    )
    return Submission("self-review:" + key, f"Review: {task.title}"[:240], prompt, RequestSource(REVIEW_CONVERSATION, SelfReview(task.id)))


def daily_review(day: date) -> Submission:
    """The day's identity makes its review idempotent however many runs request it."""
    subject = day.isoformat()
    prompt = (
        f"Review your own work on {subject}. Read it with work_history (day {subject}), follow every next_offset, "
        "and inspect relevant task_id details before drawing conclusions. Look for patterns across tasks: "
        "repeated failures, repeated questions, goals the user had to correct, and slow or roundabout methods. " + _METHOD
    )
    return Submission("self-review:day:" + subject, f"Daily review: {subject}", prompt, RequestSource(REVIEW_CONVERSATION, SelfReview(subject)))


def day_window(day: date) -> tuple[float, float]:
    """The local day's start and end as UTC seconds."""
    start = datetime.combine(day, time()).astimezone()
    return start.timestamp(), (start + timedelta(days=1)).timestamp()


def worked_on(tasks: Iterable[Task], day: date) -> tuple[Task, ...]:
    """The reviewable tasks updated during the local day."""
    start, end = day_window(day)
    return tuple(task for task in tasks if reviewable(task) and start <= task.updated_at < end)


@dataclass(frozen=True, slots=True)
class TaskRecord:
    """One task as its review reads it."""

    task: Task
    actions: tuple[Action, ...]
    revisions: tuple[GoalRevision, ...]
    responses: tuple[Response, ...]


def _state_text(task: Task) -> str:
    match task.state:
        case Completed(result=result):
            return "completed: " + result[:600]
        case Failed(reason=reason):
            return "failed: " + reason[:600]
        case Waiting(reason=Blocked(reason=reason)):
            return "blocked: " + reason[:600]
        case Waiting(reason=Question(text=question)):
            return "waiting for the user's answer: " + question[:600]
        case _:
            return phase(task.state)


def _record_lines(record: TaskRecord) -> Iterator[str]:
    task = record.task
    yield f"## {task.id}: {task.title}"
    yield f"Source: {task.source.kind}; updated {datetime.fromtimestamp(task.updated_at).astimezone():%Y-%m-%d %H:%M}; {_state_text(task)}"
    for revision in record.revisions:
        yield f"Goal revision {revision.revision}: {revision.prompt[:800]}"
    for response in record.responses:
        reply = response.reply.text[:400] if isinstance(response.reply, TextAnswer) else response.reply.value
        match response.request:
            case Question(text=question):
                yield f"Asked: {question[:400]}; answered: {reply}"
            case Approval(title=title):
                yield f"Approval '{title[:200]}': {reply}"
            case _:
                assert_never(response.request)
    for action in record.actions:
        match action.outcome:
            case ActionUncertain(reason=detail) | ActionNotApplied(reason=detail):
                pass
            case ActionReturned(summary=detail):
                pass
            case ActionVerified(evidence=detail):
                pass
            case ActionPending.RUNNING:
                detail = "No settled outcome recorded."
            case _:
                assert_never(action.outcome)
        yield f"Action {action.specification.tool} ({outcome_kind(action.outcome)}) [{action.id}; run {action.run_id}]: {detail[:800]}"
    if record.actions:
        kinds = Counter(outcome_kind(action.outcome) for action in record.actions)
        yield "Actions: " + ", ".join(f"{count} {kind}" for kind, count in sorted(kinds.items()))


def describe_history(records: Iterable[TaskRecord], *, limit: int = 40_000) -> str:
    """The reviewed tasks newest first, bounded for the model."""
    text = "\n\n".join("\n".join(_record_lines(record)) for record in records)
    if not text:
        return "No tasks match."
    return text if len(text) <= limit else text[:limit] + f"\n[cut: showing {limit} of {len(text)} characters]"


def describe_history_page(tasks: Sequence[Task], offset: int, recent: int) -> str:
    """Whole task summaries keep verbose diagnostics from hiding later outcomes.

    Twenty summaries fit the model's output budget even with long results.
    Offsets refer to the same newest-first selection; task_id drills into evidence.
    """
    page = tasks[offset : offset + min(recent, 20)]
    lines = tuple(
        f"## {task.id}: {task.title}\n"
        f"Updated {datetime.fromtimestamp(task.updated_at).astimezone():%Y-%m-%d %H:%M}; {_state_text(task)}\n"
        f"Goal revisions: {task.goal_revision}; detail: work_history(task_id='{task.id}')."
        for task in page
    )
    end = offset + len(page)
    continuation = f"next_offset: {end}" if end < len(tasks) else "next_offset: none"
    return ("\n\n".join(lines) or "No tasks match.") + f"\n\n{continuation}; matched tasks in scan: {len(tasks)}."


def lesson(name: str, rule: str, task_id: str, at: float) -> Preference:
    """A lesson's identity follows its name, so saving the same name updates it."""
    identity = "lesson:" + hashlib.sha256(name.strip().casefold().encode("utf-8")).hexdigest()[:32]
    return Preference(identity, name.strip(), rule.strip(), LESSON_SOURCE + task_id, at)


def agent_lesson(record: ContextRecord | None) -> Preference | None:
    """The record when the agent wrote it; the user's own preferences are never the agent's to retire."""
    match record:
        case Preference(source=source) if source.startswith(LESSON_SOURCE):
            return record
        case _:
            return None


class ReviewingRunner:
    """After each run, submit the review its signals call for and the previous day's review."""

    __slots__ = ("clock", "runner")

    def __init__(self, runner: Runner, clock: Callable[[], datetime]) -> None:
        self.runner, self.clock = runner, clock

    def run_work(self, claim: Claim, store: TaskStore, log: Log, stop: threading.Event) -> Outcome:
        outcome = self.runner.run_work(claim, store, log, stop)
        task = claim.task
        if not reviewable(task):
            return outcome
        now = self.clock()
        found = signals(outcome, store.actions(task.id, limit=100), store.revisions(task.id), store.responses(task.id))
        reviews = [task_review(task, claim.run.run_id, found)] if found else []
        yesterday = now.date() - timedelta(days=1)
        if worked_on(store.list_tasks(limit=200), yesterday):
            reviews.append(daily_review(yesterday))
        for review in reviews:
            store.submit(review.id, review.title, review.prompt, review.source, at=now.timestamp(), priority=REVIEW_PRIORITY)
        return outcome
