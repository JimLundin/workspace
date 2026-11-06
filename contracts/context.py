"""Saved context the agent works from: explicit preferences and dated project notes.

The records are values both the assistant's store and the desktop's views read;
`automation.context` stores and selects them.
"""

from dataclasses import dataclass
from math import isfinite

MAX_CONTENT = 4000
MAX_SOURCE = 1000


def bounded_text(value: object, name: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip() or "\0" in value or len(value) > limit:
        raise ValueError(f"{name} must contain 1-{limit} characters and no null characters.")
    return value


def timestamp(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value) or value < 0:
        raise ValueError("Context timestamps must be finite, nonnegative UTC seconds.")
    return float(value)


@dataclass(frozen=True, slots=True)
class Preference:
    id: str
    name: str
    value: str
    source: str
    updated_at: float

    def __post_init__(self) -> None:
        bounded_text(self.id, "Context identity", 128)
        bounded_text(self.name, "Preference name", 160)
        bounded_text(self.value, "Preference value", MAX_CONTENT)
        bounded_text(self.source, "Preference source", MAX_SOURCE)
        timestamp(self.updated_at)


@dataclass(frozen=True, slots=True)
class ProjectNote:
    id: str
    project: str
    text: str
    source: str
    observed_at: float
    valid_until: float

    def __post_init__(self) -> None:
        bounded_text(self.id, "Context identity", 128)
        bounded_text(self.project, "Project name", 160)
        bounded_text(self.text, "Project note", MAX_CONTENT)
        bounded_text(self.source, "Project source", MAX_SOURCE)
        if timestamp(self.valid_until) <= timestamp(self.observed_at):
            raise ValueError("A project note must expire after its observation.")


type ContextRecord = Preference | ProjectNote
