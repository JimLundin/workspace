"""Canvas client commands and immutable publications, without effect ownership."""

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol

from contracts.attention import AttentionSnapshot
from contracts.canvas_activity import CanvasQuestion, CanvasRequest, CanvasRun
from contracts.task import TextAnswer
from contracts.work_canvas_edits import UserEdit
from contracts.work_canvas_model import CanvasDocument


@dataclass(frozen=True, slots=True)
class Announcement:
    title: str
    target: str


@dataclass(frozen=True, slots=True)
class CanvasPublication:
    document: CanvasDocument
    waiting: tuple[CanvasQuestion, ...]
    settled: frozenset[str]
    notice: Announcement | None = None
    attention: AttentionSnapshot = field(default_factory=AttentionSnapshot)


@dataclass(frozen=True, slots=True)
class Queued:
    document: CanvasDocument


@dataclass(frozen=True, slots=True)
class NotQueued:
    """The binding stays saved, so retrying or startup recovery reuses it."""

    document: CanvasDocument
    reason: str


@dataclass(frozen=True, slots=True)
class ResumeTask:
    task_id: str


class Investigating(Enum):
    ALREADY = "already"


type Continuation = Queued | NotQueued | ResumeTask | Investigating


class CanvasEdits(Protocol):
    """Commands available to a canvas client; observations belong to the owner."""

    def read(self) -> CanvasDocument: ...
    def commit(self, edit: UserEdit) -> CanvasDocument: ...
    def start(self, run: CanvasRun) -> Queued | NotQueued: ...
    def continue_work(self, work_id: str) -> Continuation: ...
    def waiting(self) -> tuple[CanvasQuestion, ...]: ...
    def answer(self, request: CanvasRequest, value: TextAnswer, deliver: Callable[[CanvasRequest, TextAnswer], bool]) -> bool: ...
