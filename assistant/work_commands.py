"""Typed task commands, plus personal-work commands for views."""

from dataclasses import dataclass

from automation.personal_work import (
    AddDocument,
    AddWebPage,
    DismissWork,
    OpenWorkSource,
    RefreshPersonalWork,
    RestoreWork,
    SaveWork,
    UnlinkWork,
)
from automation.task import Control, TextAnswer


@dataclass(frozen=True, slots=True)
class Submit:
    prompt: str


@dataclass(frozen=True, slots=True)
class ControlTask:
    task_id: str
    control: Control


@dataclass(frozen=True, slots=True)
class AnswerTask:
    task_id: str
    request_id: str
    answer: TextAnswer


type WorkCommand = Submit | ControlTask | AnswerTask

type WorkViewCommand = (
    WorkCommand | AddDocument | AddWebPage | DismissWork | RestoreWork | SaveWork | UnlinkWork | OpenWorkSource | RefreshPersonalWork
)
