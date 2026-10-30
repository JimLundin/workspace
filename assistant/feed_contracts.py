"""Pydantic contracts for feed model requests, recommendations and typed user commands."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Annotated, Literal, Protocol

from pydantic import AfterValidator, Field, StringConstraints, TypeAdapter

from assistant.feed_history import Decision, Identity
from assistant.feed_origin import Origin
from assistant.llm import Json

type Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=32)]
type Detail = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1200)]
type Priority = Annotated[int, Field(strict=True, ge=0, le=2)]
type ItemIdentity = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128, pattern=r"^[^\x00]+$")]
type Choice = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=32, pattern=r"^[^\x00]+$")]
# Command text becomes recorded decision text, whose saved contract forbids NUL.
type CommandText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1200, pattern=r"^[^\x00]+$")]


@dataclass(frozen=True, slots=True)
class ProposedSolution:
    label: Label
    kind: Literal["draft", "check", "plan"]
    detail: Detail


def _distinct(solutions: tuple[ProposedSolution, ...]) -> tuple[ProposedSolution, ...]:
    if len({option.label.casefold() for option in solutions}) != len(solutions):
        raise ValueError("Solutions need distinct concise labels.")
    return solutions


type ProposedSolutions = Annotated[tuple[ProposedSolution, ...], Field(max_length=3), AfterValidator(_distinct)]


@dataclass(frozen=True, slots=True)
class ProposedItem:
    sources: Annotated[tuple[Identity, ...], Field(min_length=1, max_length=20)]
    disposition: Literal["action", "quiet"]
    title: Annotated[str, Field(max_length=160)]
    summary: Annotated[str, Field(max_length=1800)]
    suggestion: Annotated[str, Field(max_length=1200)]
    solutions: ProposedSolutions
    priority: Priority


@dataclass(frozen=True, slots=True)
class ReviewOutput:
    items: Annotated[tuple[ProposedItem, ...], Field(max_length=20)]


@dataclass(frozen=True, slots=True)
class SourceEvidence:
    id: str
    revision: str
    source: str
    title: str
    body: str
    created_at: str | None
    date_hint: str | None
    date_hint_observed_on: str | None


@dataclass(frozen=True, slots=True)
class ReviewInput:
    reviewed_at: str
    candidates: tuple[SourceEvidence, ...]
    working_context: str


@dataclass(frozen=True, slots=True)
class FeedReply:
    item: Identity
    revision: Identity
    reply_id: Identity
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4096, pattern=r"^[^\x00]+$")]
    operation: Literal["reply"] = "reply"


@dataclass(frozen=True, slots=True)
class ReadFeed:
    operation: Literal["read"] = "read"


@dataclass(frozen=True, slots=True)
class ChooseSolution:
    item: ItemIdentity
    revision: ItemIdentity
    choice: Choice
    operation: Literal["choose"] = "choose"


@dataclass(frozen=True, slots=True)
class AnswerConsole:
    request_id: ItemIdentity
    question_index: Annotated[int, Field(strict=True, ge=0, lt=32)]
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4096, pattern=r"^[^\x00]+$")]
    operation: Literal["console_answer"] = "console_answer"


@dataclass(frozen=True, slots=True)
class SaveRule:
    text: CommandText
    operation: Literal["rule"] = "rule"


@dataclass(frozen=True, slots=True)
class ForgetRule:
    text: CommandText
    operation: Literal["forget_rule"] = "forget_rule"


@dataclass(frozen=True, slots=True)
class ClearRules:
    operation: Literal["clear_rules"] = "clear_rules"


@dataclass(frozen=True, slots=True)
class CompleteItem:
    item: ItemIdentity
    operation: Literal["done"] = "done"


@dataclass(frozen=True, slots=True)
class QuietItem:
    item: ItemIdentity
    operation: Literal["quiet"] = "quiet"


@dataclass(frozen=True, slots=True)
class DismissItem:
    item: ItemIdentity
    operation: Literal["dismiss"] = "dismiss"


@dataclass(frozen=True, slots=True)
class RejectProposal:
    item: ItemIdentity
    revision: ItemIdentity
    text: CommandText
    operation: Literal["reject"] = "reject"


@dataclass(frozen=True, slots=True, kw_only=True)
class ReviseProposal:
    """The user's correction; omitted priority keeps the current one, omitted solutions plan the suggestion."""

    item: ItemIdentity
    text: CommandText
    question: Annotated[str, StringConstraints(strip_whitespace=True, max_length=600, pattern=r"^[^\x00]*$")] = ""
    priority: Priority | None = None
    solutions: Annotated[ProposedSolutions, Field(min_length=1)] | None = None
    operation: Literal["propose"] = "propose"


type ItemEdit = CompleteItem | QuietItem | DismissItem | RejectProposal | ReviseProposal
type BoardEdit = Annotated[
    SaveRule | ForgetRule | ClearRules | CompleteItem | QuietItem | DismissItem | RejectProposal | ReviseProposal,
    Field(discriminator="operation"),
]
type FeedCommand = Annotated[ReadFeed | ChooseSolution | AnswerConsole | FeedReply | BoardEdit, Field(discriminator="operation")]


@dataclass(frozen=True, slots=True)
class SolutionContext:
    item: str
    title: str
    summary: str
    revision: str
    suggested_solution: str
    source_revisions: tuple[tuple[str, str], ...]


REVIEW_OUTPUT = TypeAdapter(ReviewOutput)
REVIEW_INPUT = TypeAdapter(ReviewInput)
SOURCE_EVIDENCE = TypeAdapter(SourceEvidence)
FEED_REPLY = TypeAdapter(FeedReply)
BOARD_EDIT = TypeAdapter(BoardEdit)
FEED_COMMAND = TypeAdapter(FeedCommand)
_SCHEMA = TypeAdapter(dict[str, Json])


class SchemaSource(Protocol):
    def json_schema(self) -> object: ...


def reply_schema() -> dict[str, Json]:
    """Derive the tool contract; the tool name already fixes the internal operation."""
    source: SchemaSource = FEED_REPLY
    observed = source.json_schema()
    schema = _SCHEMA.validate_python(observed)
    properties = _SCHEMA.validate_python(schema.get("properties"))
    return {**schema, "properties": {key: value for key, value in properties.items() if key != "operation"}, "additionalProperties": False}


@dataclass(frozen=True, slots=True)
class BridgeEndpoint:
    url: str
    token: str


BRIDGE_ENDPOINT = TypeAdapter(BridgeEndpoint)
SOLUTION_CONTEXT = TypeAdapter(SolutionContext)


class Disposition(Enum):
    ACTION = "action"
    QUIET = "quiet"
    USER_QUIET = "user_quiet"
    DONE = "done"
    DISMISSED = "dismissed"
    REJECTED = "rejected"


class SolutionKind(Enum):
    DRAFT = "draft"
    CHECK = "check"
    PLAN = "plan"


@dataclass(frozen=True, slots=True)
class StoredSolution:
    id: str
    label: str
    kind: SolutionKind
    detail: str
    recommended: bool = field(kw_only=True)


@dataclass(frozen=True, slots=True)
class StoredItem:
    id: str
    refs: tuple[tuple[str, str], ...]
    origins: tuple[Origin, ...]
    title: str
    summary: str
    suggestion: str
    question: str
    priority: int
    at: float
    disposition: Disposition
    solutions: tuple[StoredSolution, ...]
    revision: str
    decision: str
    reviewed_on: str | None


@dataclass(frozen=True, slots=True)
class StoredBoard:
    rules: tuple[str, ...] = ()
    items: tuple[StoredItem, ...] = ()
    history: tuple[Decision, ...] = ()
    review_version: int = field(default=0, kw_only=True)


STORED_BOARD = TypeAdapter(StoredBoard)


@dataclass(frozen=True, slots=True, kw_only=True)
class ConsoleOptionQuestion:
    index: int
    text: str
    multiple: bool
    options: tuple[str, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class ConsolePendingRequest:
    id: str
    provider: str
    title: str
    detail: str
    created_at: str | None
    approval: bool
    questions: tuple[ConsoleOptionQuestion, ...]


@dataclass(frozen=True, slots=True)
class RejectedDecision:
    item: str
    title: str
    reason: str


@dataclass(frozen=True, slots=True, kw_only=True)
class FeedSnapshot:
    """One public feed observation; encrypted retry prompts never enter this contract."""

    rules: tuple[str, ...]
    items: tuple[StoredItem, ...]
    review_version: int
    working_context: str
    reviewed_at: str
    decisions: tuple[RejectedDecision, ...]
    total_actions: int
    quiet_updates: int
    focus: str | None
    status: str
    pending: int
    unavailable_items: tuple[str, ...]
    quiet_reactions: int
    sources: tuple[SourceEvidence, ...]
    console_questions: tuple[ConsolePendingRequest, ...]


@dataclass(frozen=True, slots=True)
class QueuedHandoff:
    queued: str
    item: str
    decision: str
    accepted: Literal[True] = field(default=True, kw_only=True)


@dataclass(frozen=True, slots=True)
class ChosenHandoff:
    queued: str
    item: str
    decision: str
    choice: str
    accepted: Literal[True] = field(default=True, kw_only=True)


@dataclass(frozen=True, slots=True)
class ConsoleAnswered:
    answered: str
    question_index: int


@dataclass(frozen=True, slots=True)
class FeedRejected:
    error: str
    accepted: Literal[False] = field(default=False, kw_only=True)
