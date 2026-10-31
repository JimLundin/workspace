"""Typed work commands: views and the agent issue them, and the work service applies each one."""

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
from automation.routines import Trigger
from automation.task import Control, Reply


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
    answer: Reply


@dataclass(frozen=True, slots=True)
class RefreshApproval:
    task_id: str
    request_id: str


@dataclass(frozen=True, slots=True)
class CreateRoutine:
    title: str
    instruction: str
    trigger: Trigger


@dataclass(frozen=True, slots=True)
class UpdateRoutine:
    routine_id: str
    revision: int
    title: str
    instruction: str
    trigger: Trigger


@dataclass(frozen=True, slots=True)
class EnableRoutine:
    routine_id: str


@dataclass(frozen=True, slots=True)
class DisableRoutine:
    routine_id: str


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
    Submit
    | FollowUp
    | Redirect
    | ControlTask
    | AnswerTask
    | RefreshApproval
    | CreateRoutine
    | UpdateRoutine
    | EnableRoutine
    | DisableRoutine
    | AddPreference
    | UpdatePreference
    | AddProjectNote
    | UpdateProjectNote
    | RemoveContext
    | AddDocument
    | AddWebPage
    | DismissWork
    | RestoreWork
    | SaveWork
    | UnlinkWork
    | OpenWorkSource
    | RefreshPersonalWork
)
