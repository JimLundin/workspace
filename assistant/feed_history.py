"""Immutable, bounded work-feed decisions and exact retryable handoffs."""

from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, TypeAdapter

type Identity = Annotated[str, StringConstraints(min_length=1, max_length=128, pattern=r"^[^\x00]+$")]
type Prompt = Annotated[str, StringConstraints(min_length=1, max_length=64000, pattern=r"^[^\x00]+$")]
type DecisionText = Annotated[str, StringConstraints(max_length=4096, pattern=r"^[^\x00]*$")]
type DecisionTime = Annotated[float, Field(ge=0, allow_inf_nan=False)]


@dataclass(frozen=True, slots=True)
class Handoff:
    task_id: Identity
    prompt: Prompt


@dataclass(frozen=True, slots=True)
class BoardDecision:
    """One user edit of the board, scoped to the captured work rather than a guessed preference."""

    id: Identity
    # The board edits a decision records; each matches its edit's own tag.
    operation: Literal["reject", "propose", "done", "quiet", "dismiss", "rule", "forget_rule", "clear_rules"]
    item: Annotated[str, Field(max_length=128)]
    revision: Annotated[str, Field(max_length=128)]
    title: Annotated[str, Field(max_length=160)]
    summary: Annotated[str, Field(max_length=1800)]
    text: DecisionText
    at: DecisionTime

    def describe(self) -> str:
        return _described(self, "")


@dataclass(frozen=True, slots=True)
class HandoffDecision:
    """A chosen solution or a reply: the user's instruction, handed to the work agent as one task."""

    id: Identity
    operation: Literal["choose", "reply"]
    item: Annotated[str, Field(max_length=128)]
    revision: Annotated[str, Field(max_length=128)]
    title: Annotated[str, Field(max_length=160)]
    summary: Annotated[str, Field(max_length=1800)]
    text: DecisionText
    at: DecisionTime
    handoff: Handoff

    def describe(self) -> str:
        return _described(self, f"\nTask: {self.handoff.task_id}")


type Decision = Annotated[BoardDecision | HandoffDecision, Field(discriminator="operation")]


def _described(decision: BoardDecision | HandoffDecision, task: str) -> str:
    return (
        f"Decision {decision.id} ({decision.operation}) at {decision.at}\nWork: {decision.title} ({decision.item}, {decision.revision})"
        f"\nCaptured request: {decision.summary}\nUser decision: {decision.text}{task}"
    )


_DECISIONS = TypeAdapter(tuple[Decision, ...])


def restored_history(value: object) -> tuple[Decision, ...]:
    history = _DECISIONS.validate_python(value)
    if len(history) > 200:
        raise ValueError("Saved feed history exceeds its bound.")
    if len(frozenset(entry.id for entry in history)) != len(history):
        raise ValueError("Saved feed decisions have duplicate identities.")
    return history
