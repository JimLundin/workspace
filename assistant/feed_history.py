"""Immutable, bounded work-feed decisions and exact retryable handoffs."""

from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, TypeAdapter

type Identity = Annotated[str, StringConstraints(min_length=1, max_length=128, pattern=r"^[^\x00]+$")]
type Prompt = Annotated[str, StringConstraints(min_length=1, max_length=64000, pattern=r"^[^\x00]+$")]
type DecisionText = Annotated[str, StringConstraints(max_length=4096, pattern=r"^[^\x00]*$")]
type DecisionTime = Annotated[float, Field(ge=0, allow_inf_nan=False)]

type DecisionKind = Literal["choice", "reply", "reject", "propose", "done", "quiet", "dismiss", "rule", "forget_rule", "clear_rules"]


@dataclass(frozen=True, slots=True)
class Handoff:
    task_id: Identity
    prompt: Prompt


@dataclass(frozen=True, slots=True)
class Decision:
    """One user decision, scoped to the captured work rather than a guessed preference."""

    id: Identity
    kind: DecisionKind
    item: Annotated[str, Field(max_length=128)]
    revision: Annotated[str, Field(max_length=128)]
    title: Annotated[str, Field(max_length=160)]
    summary: Annotated[str, Field(max_length=1800)]
    text: DecisionText
    at: DecisionTime
    handoff: Handoff | None = None

    def describe(self) -> str:
        task = f"\nTask: {self.handoff.task_id}" if self.handoff is not None else ""
        return (
            f"Decision {self.id} ({self.kind}) at {self.at}\nWork: {self.title} ({self.item}, {self.revision})"
            f"\nCaptured request: {self.summary}\nUser decision: {self.text}{task}"
        )


_DECISIONS = TypeAdapter(tuple[Decision, ...])


def restored_history(value: object) -> tuple[Decision, ...]:
    history = _DECISIONS.validate_python(value)
    if len(history) > 200:
        raise ValueError("Saved feed history exceeds its bound.")
    if len(frozenset(entry.id for entry in history)) != len(history):
        raise ValueError("Saved feed decisions have duplicate identities.")
    return history
