"""The work service's immutable published observation: tasks, context and problems."""

from dataclasses import dataclass, field

from contracts.context import ContextRecord
from contracts.personal_work import PersonalView
from contracts.task import Action, Task, identifier, text


@dataclass(frozen=True, slots=True)
class SubmissionProblem:
    task_id: str
    reason: str

    def __post_init__(self) -> None:
        identifier(self.task_id, "submission identity")
        text(self.reason, "submission problem", maximum=8_000)


@dataclass(frozen=True, slots=True, kw_only=True)
class ReplyProblem:
    task_id: str
    request_id: str
    receipt_id: str
    reason: str

    def __post_init__(self) -> None:
        identifier(self.task_id, "reply task identity")
        identifier(self.request_id, "reply request identity")
        identifier(self.receipt_id, "reply receipt identity")
        text(self.reason, "reply problem", maximum=8_000)


@dataclass(frozen=True, slots=True)
class WorkSnapshot:
    tasks: tuple[Task, ...] = ()
    context: tuple[ContextRecord, ...] = ()
    status: str = ""
    submission_problems: tuple[SubmissionProblem, ...] = ()
    reply_problems: tuple[ReplyProblem, ...] = ()
    personal: PersonalView = field(default_factory=PersonalView)
    actions: tuple[Action, ...] = ()
