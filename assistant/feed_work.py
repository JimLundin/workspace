"""Work-feed context from the existing task journal and explicit project memory."""

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from itertools import accumulate, pairwise
from typing import assert_never

from assistant.feed_history import Decision, HandoffDecision
from assistant.feed_triage import Board
from automation.activity import ContextSnapshot
from automation.context import ContextSelection, ContextStore, select_context
from automation.store import TaskStore
from contracts.context import ProjectNote
from contracts.task import (
    Blocked,
    Completed,
    Failed,
    Interrupted,
    Question,
    Response,
    Running,
    Task,
    TaskStatus,
    Until,
    Waiting,
    phase,
)


def projects(selection: ContextSelection) -> tuple[str, ...]:
    return tuple(record.project.casefold() for record in (*selection.records, *selection.stale) if isinstance(record, ProjectNote))


def matches_project(text: str, names: tuple[str, ...]) -> bool:
    return any(re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)", text, re.IGNORECASE) is not None for name in names)


def prioritized_decisions(history: tuple[Decision, ...], names: tuple[str, ...]) -> tuple[Decision, ...]:
    def rank(entry: Decision) -> tuple[bool, float]:
        return matches_project("\n".join((entry.title, entry.summary, entry.text)), names), entry.at

    return tuple(sorted(history, key=rank, reverse=True))


@dataclass(frozen=True, slots=True)
class TaskEvidence:
    task: Task
    responses: tuple[Response, ...]

    def describe(self) -> str:
        task = self.task
        detail: str
        match task.state:
            case Completed(result, _):
                detail = result[:2000]
            case Waiting(reason):
                match reason:
                    case Question(_, question, _):
                        detail = question
                    case Blocked(explanation) | Until(_, explanation):
                        detail = explanation
                    case _ as unreachable:
                        assert_never(unreachable)
            case Failed(reason) | Interrupted(reason=reason):
                detail = reason
            case Running() | TaskStatus():
                detail = task.checkpoint.summary[:2000] if task.checkpoint is not None else ""
            case _ as unreachable:
                assert_never(unreachable)
        replies = [
            f"Question: {response.request.text[:600]}\nUser answer at {response.at}: {response.reply.text[:1200]}" for response in self.responses[-8:]
        ]
        return (
            f"Task {task.id}: {task.title}\nState: {phase(task.state)}; updated at {task.updated_at}"
            f"\nGoal: {task.prompt[:1200]}\nProgress or result: {detail[:2000]}\n" + "\n".join(replies)
        )


def bounded(rows: Iterable[str], budget: int) -> str:
    """Publish complete evidence rows within this feed request's character budget."""
    offered = tuple(rows)

    def spent(used: int, row: str) -> int:
        cost = len(row) + 2
        return used + cost if used + cost <= budget else used

    totals = pairwise(accumulate(offered, spent, initial=0))
    return "\n\n".join(row for row, (before, after) in zip(offered, totals, strict=True) if after > before)


@dataclass(frozen=True, slots=True)
class WorkingContext:
    saved: ContextSelection = field(default_factory=ContextSelection)
    tasks: tuple[TaskEvidence, ...] = ()
    desktop: ContextSnapshot | None = None

    def describe(self, board: Board) -> str:
        names = projects(self.saved)
        # Relevance precedes recency within the context budget. A busy unrelated
        # project must not displace the prior decision for this request.
        decisions = prioritized_decisions(board.history, names)

        def rank(entry: TaskEvidence) -> tuple[bool, float]:
            return matches_project(entry.task.title + "\n" + entry.task.prompt, names), entry.task.updated_at

        tasks = sorted(self.tasks, key=rank, reverse=True)
        desktop = (
            "\n".join(f"{item.window.exe}: {item.window.title[:600]} (agent active: {item.agent_active})" for item in self.desktop.recent[-6:])
            if self.desktop is not None
            else "Unavailable"
        )
        return (
            "Saved project context:\n"
            + self.saved.describe()
            + "\n\nTask journal:\n"
            + bounded((entry.describe() for entry in tasks), 16000)
            + "\n\nUser decisions:\n"
            + bounded((entry.describe() for entry in decisions), 16000)
            + "\n\nOpen work:\n"
            + bounded((f"{item.title} ({item.identity})\n{item.summary}\n{item.suggestion}" for item in board.actions), 8000)
            + "\n\nRecent desktop activity (temporary observation):\n"
            + desktop
            + "\nCoverage is bounded; omitted work may exist. Refresh old facts before acting."
        )


@dataclass(frozen=True, slots=True)
class FeedWork:
    """Read existing stores; no second task store, automatic preferences or desktop persistence."""

    tasks: TaskStore
    context: ContextStore
    activity: Callable[[], ContextSnapshot]

    def read(self, board: Board, query: str, now: float) -> WorkingContext:
        # Query, board and time bind one review: linked work is fetched even when
        # newer unrelated tasks have pushed it outside the journal's recent page.
        selected = select_context(self.context.list(), query[:20000], now)
        names = projects(selected)
        decisions = prioritized_decisions(board.history, names)
        linked = tuple(entry.handoff.task_id for entry in decisions if isinstance(entry, HandoffDecision))[:40]
        tasks = self.tasks.get_many(linked)
        known = frozenset(task.id for task in tasks)
        tasks = (*tasks, *(task for task in self.tasks.list_tasks(limit=40) if task.id not in known))[:60]
        return WorkingContext(
            selected,
            tuple(TaskEvidence(task, self.tasks.responses(task.id)) for task in tasks),
            self.activity(),
        )
