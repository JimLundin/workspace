"""The self-review tool family: the agent reads its own work history and keeps lessons that shape later runs."""

import time
from dataclasses import dataclass
from datetime import date
from typing import Annotated, Final

from pydantic import Field, TypeAdapter

from assistant.agent_tools import NO_ARGUMENTS, Args, ArgumentError, Display, NoArguments, Output, Session, Tool, argument_spec, fixed, typed_run
from automation.actions import Change, Evidence, Observation
from automation.context import ContextStore
from automation.execution import WorkExecution
from automation.self_review import TaskRecord, agent_lesson, describe_history, describe_history_page, lesson, worked_on
from automation.store import TaskStore
from contracts.context import Preference
from contracts.task import ActionUncertain, ActionVerified, Task

INSTRUCTIONS: Final = (
    "You improve from your own work. Saved lessons from earlier reviews appear with the saved preferences; follow them. "
    "When the user corrects you, tells you to do something differently or asks you to remember something, save it with "
    "save_lesson. When the user asks you to improve yourself or how you handle something, read the evidence with "
    "work_history first, then save lessons and change Workspace's source as that evidence calls for."
)

type Text = Annotated[str, Field(strict=True, min_length=1)]


@dataclass(frozen=True, slots=True)
class HistoryArguments:
    task_id: Annotated[str, Field(strict=True)] = ""
    day: Annotated[str, Field(strict=True, description="A local date, YYYY-MM-DD.")] = ""
    recent: Annotated[int, Field(strict=True, ge=1, le=100, description="Summary page size, capped at 20 whole tasks.")] = 20
    offset: Annotated[int, Field(strict=True, ge=0, le=1_000, description="Use next_offset to continue the same day/recent selection.")] = 0


@dataclass(frozen=True, slots=True)
class LessonArguments:
    name: Annotated[str, Field(strict=True, min_length=1, max_length=160)]
    rule: Annotated[str, Field(strict=True, min_length=1, max_length=2_000)]


@dataclass(frozen=True, slots=True)
class LessonIdentity:
    id: Text


_HISTORY: Final = TypeAdapter(HistoryArguments)
_LESSON: Final = TypeAdapter(LessonArguments)
_IDENTITY: Final = TypeAdapter(LessonIdentity)
_LESSONS: Final = "lessons"


class SelfReviewTools:
    """Reads the task journal across tasks and writes only the agent's own lessons."""

    __slots__ = ("lessons", "session", "store", "task_id")

    def __init__(self, session: Session, work: WorkExecution, lessons: ContextStore) -> None:
        self.session, self.lessons = session, lessons
        self.store: TaskStore = work.store
        self.task_id = work.claim.task.id
        """The running task, which each saved lesson cites."""

    def tools(self) -> tuple[Tool, ...]:
        return (
            Tool(
                argument_spec(
                    "work_history",
                    "Enumerate bounded task outcome summaries with explicit next_offset; repeat the same day/recent selection "
                    "with that offset until exhausted. Day filters the newest 1000 journal tasks; scan coverage is reported. "
                    "Give task_id to drill into existing action diagnostics and answers (offset must be zero).",
                    _HISTORY,
                ),
                typed_run(_HISTORY, self.work_history),
                fixed(Observation((), Evidence.NONE)),
                Display.PUBLIC,
            ),
            Tool(
                argument_spec("list_lessons", "List the lessons you saved from earlier work, with their IDs.", NO_ARGUMENTS),
                typed_run(NO_ARGUMENTS, self.list_lessons),
                fixed(Observation((), Evidence.NONE)),
                Display.PUBLIC,
            ),
            Tool(
                argument_spec(
                    "save_lesson",
                    "Save or update a lesson: one short, specific rule that every later run follows. Saving an existing name replaces it.",
                    _LESSON,
                ),
                typed_run(_LESSON, self.save_lesson),
                fixed(Change((_LESSONS,))),
                Display.PUBLIC,
            ),
            Tool(
                argument_spec("remove_lesson", "Remove a lesson you saved that proved wrong or was superseded.", _IDENTITY),
                typed_run(_IDENTITY, self.remove_lesson),
                fixed(Change((_LESSONS,))),
                Display.PUBLIC,
            ),
        )

    def _history(self, request: HistoryArguments) -> str:
        """Enumeration reads task outcomes only; explicit identity retains diagnostics."""
        if request.task_id:
            if request.day or request.offset:
                raise ArgumentError("task_id detail cannot be combined with day or offset.")
            found = self.store.get(request.task_id)
            if found is None:
                raise ArgumentError(f"there's no task {request.task_id}.")
            record = TaskRecord(found, self.store.actions(found.id, limit=100), self.store.responses(found.id))
            return describe_history((record,)) + "\nDetail coverage: newest 100 actions; current-goal answers."
        tasks: tuple[Task, ...] = self.store.list_tasks(limit=1_000)
        coverage = (
            "Scan coverage: newest 1000 journal tasks; older tasks may exist outside this scan."
            if len(tasks) == 1_000
            else f"Scan coverage: all {len(tasks)} journal tasks."
        )
        if request.day:
            try:
                day = date.fromisoformat(request.day)
            except ValueError as error:
                raise ArgumentError("day must be a date in the form YYYY-MM-DD.") from error
            tasks = worked_on(tasks, day)
        return describe_history_page(tasks, request.offset, request.recent) + "\n" + coverage

    def work_history(self, args: Args, request: HistoryArguments) -> Output:
        return self.session.effect(args.operation, lambda: Output(self._history(request)))

    def list_lessons(self, args: Args, _request: NoArguments) -> Output:
        def read() -> Output:
            saved = tuple(found for record in self.lessons.list() if (found := agent_lesson(record)) is not None)
            return Output("\n".join(f"{item.id}: {item.name}: {item.value}" for item in saved) or "No lessons saved yet.")

        return self.session.effect(args.operation, read)

    def save_lesson(self, args: Args, request: LessonArguments) -> Output:
        record = lesson(request.name, request.rule, self.task_id, time.time())

        def save() -> Output:
            existing = self.lessons.get(record.id)
            if existing is not None and agent_lesson(existing) is None:
                raise ArgumentError("that name belongs to one of the user's own preferences; choose another.")
            self.lessons.save(record)
            return Output(f"Saved lesson {record.id}.")

        return self.session.effect(args.operation, save, lambda _: self._readback(record.id, record))

    def remove_lesson(self, args: Args, request: LessonIdentity) -> Output:
        if agent_lesson(self.lessons.get(request.id)) is None:
            raise ArgumentError("only lessons you saved can be removed; list_lessons shows them.")

        def remove() -> Output:
            self.lessons.remove(request.id)
            return Output("Removed.")

        return self.session.effect(args.operation, remove, lambda _: self._readback(request.id, None))

    def _readback(self, identity: str, expected: Preference | None) -> ActionVerified | ActionUncertain:
        if self.lessons.get(identity) == expected:
            return ActionVerified("The saved lessons read back as intended.")
        return ActionUncertain("The saved lessons did not read back as intended.")
