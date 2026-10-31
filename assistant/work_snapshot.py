"""The work service's immutable published observation: tasks, reviews, routines, context and problems."""

from dataclasses import dataclass, field

from automation.context import ContextRecord
from automation.execution import ApprovalReview
from automation.personal_work import PersonalView
from automation.routines import RoutineSummary
from automation.task import Action, Task, identifier, text


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
    routines: tuple[RoutineSummary, ...] = ()
    context: tuple[ContextRecord, ...] = ()
    status: str = ""
    reviews: tuple[ApprovalReview, ...] = ()
    submission_problems: tuple[SubmissionProblem, ...] = ()
    reply_problems: tuple[ReplyProblem, ...] = ()
    personal: PersonalView = field(default_factory=PersonalView)
    actions: tuple[Action, ...] = ()
