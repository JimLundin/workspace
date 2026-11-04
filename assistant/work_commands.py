"""Typed task and context commands, plus personal-work commands for views."""

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
class FollowUp:
    task_id: str
    prompt: str


@dataclass(frozen=True, slots=True)
class Redirect:
    task_id: str
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


@dataclass(frozen=True, slots=True)
class AddPreference:
    name: str
    value: str
    source: str


@dataclass(frozen=True, slots=True)
class UpdatePreference:
    identity: str
    name: str
    value: str
    source: str


@dataclass(frozen=True, slots=True)
class AddProjectNote:
    project: str
    text: str
    source: str
    valid_for: int


@dataclass(frozen=True, slots=True)
class UpdateProjectNote:
    identity: str
    project: str
    text: str
    source: str
    valid_for: int


@dataclass(frozen=True, slots=True)
class RemoveContext:
    identity: str


type WorkCommand = (
    Submit | FollowUp | Redirect | ControlTask | AnswerTask | AddPreference | UpdatePreference | AddProjectNote | UpdateProjectNote | RemoveContext
)

type WorkViewCommand = (
    WorkCommand | AddDocument | AddWebPage | DismissWork | RestoreWork | SaveWork | UnlinkWork | OpenWorkSource | RefreshPersonalWork
)
