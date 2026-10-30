"""Validated console requests and exact answers, independent of terminal rendering."""

import json
from dataclasses import dataclass, field, replace
from enum import Enum, auto
from typing import cast


class Provider(Enum):
    CODEX = "Codex"
    CLAUDE = "Claude Code"


class State(Enum):
    WAITING = auto()
    ANSWERED = auto()
    EXPIRED = auto()
    INFORMATION = auto()


@dataclass(frozen=True, slots=True)
class Option:
    label: str
    description: str = ""


@dataclass(frozen=True, slots=True)
class Question:
    text: str
    options: tuple[Option, ...] = ()
    multiple: bool = field(default=False, kw_only=True)


@dataclass(frozen=True, slots=True)
class Request:
    identity: str
    provider: Provider
    session: str
    cwd: str
    title: str
    detail: str
    questions: tuple[Question, ...]
    created_at: float
    approval: bool = field(default=False, kw_only=True)
    state: State = State.WAITING
    answers: tuple[tuple[int, str], ...] = ()


@dataclass(frozen=True, slots=True)
class Answer:
    request: str
    question: int
    text: str


@dataclass(frozen=True, slots=True)
class Dismiss:
    request: str


type Command = Answer | Dismiss


def text(value: object, limit: int = 4096, *, default: str = "") -> str:
    if value is None:
        return default
    if not isinstance(value, str) or len(value) > limit or "\0" in value:
        raise ValueError("Invalid console request text.")
    return value


def object_value(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("Invalid console hook data.")
    result: dict[str, object] = {}
    for key, item in cast(dict[object, object], value).items():
        if not isinstance(key, str):
            raise ValueError("Invalid console hook data.")
        result[key] = item
    return result


def list_value(value: object) -> list[object]:
    if not isinstance(value, list):
        raise ValueError("Invalid console hook list.")
    return cast(list[object], value)


def request(provider: Provider, raw: object, identity: str, at: float) -> Request:
    data = object_value(raw)
    session = text(data.get("session_id"), 512)
    if not session:
        raise ValueError("Console request has no session identity.")
    cwd = text(data.get("cwd"), 4096)
    event = text(data.get("hook_event_name"), 64)
    tool = text(data.get("tool_name"), 256)
    if event in ("Stop", "Notification"):
        detail = text(data.get("message", data.get("last_assistant_message")), 16_000)
        title = "Agent needs your attention" if event == "Notification" else "Agent finished a turn"
        return Request(identity, provider, session, cwd, title, detail, (), at, state=State.INFORMATION)
    inputs = object_value(data.get("tool_input"))
    if event == "PermissionRequest":
        detail = json.dumps(inputs, ensure_ascii=False)[:12_000]
        return Request(
            identity,
            provider,
            session,
            cwd,
            f"Approve {tool or 'an action'}?",
            detail,
            (Question("Allow this action?", (Option("Approve"), Option("Decline"))),),
            at,
            approval=True,
        )
    if event != "PreToolUse" or not tool.endswith(("AskUserQuestion", "request_user_input", "request_user_input_async")):
        raise ValueError("Unsupported console hook event.")
    rows = list_value(inputs.get("questions"))
    if not 1 <= len(rows) <= 8:
        raise ValueError("Console request must contain bounded questions.")
    questions: list[Question] = []
    for raw_question in rows:
        row = object_value(raw_question)
        prompt = text(row.get("question", row.get("title")), 8000)
        if not prompt:
            raise ValueError("Console question is empty.")
        choices = list_value(row.get("options", []))
        if len(choices) > 12:
            raise ValueError("Invalid console choices.")
        options: list[Option] = []
        for choice in choices:
            if isinstance(choice, str):
                options.append(Option(text(choice, 1024)))
            else:
                option = object_value(choice)
                options.append(Option(text(option.get("label"), 1024), text(option.get("description"), 4096)))
        multiple = row.get("multiSelect", False)
        if not isinstance(multiple, bool):
            raise ValueError("Invalid console selection mode.")
        questions.append(Question(prompt, tuple(options), multiple=multiple))
    return Request(identity, provider, session, cwd, "Your answer is needed", "", tuple(questions), at)


def answered(current: Request, answer: Answer) -> Request | None:
    if current.identity != answer.request or current.state is not State.WAITING or not 0 <= answer.question < len(current.questions):
        return None
    if any(index == answer.question for index, _ in current.answers) or not answer.text.strip() or len(answer.text) > 8000:
        return None
    if sum(len(value.encode("utf-8")) for _, value in current.answers) + len(answer.text.encode("utf-8")) > 24_000:
        return None
    if current.approval and answer.text not in ("Approve", "Decline"):
        return None
    replies = (*current.answers, (answer.question, answer.text.strip()))
    return replace(current, answers=replies, state=State.ANSWERED if len(replies) == len(current.questions) else State.WAITING)


def hook_output(provider: Provider, raw: object, current: Request) -> dict[str, object]:
    """Translate an explicit user answer to each CLI's documented hook control."""
    if current.state is not State.ANSWERED:
        return {}  # Disconnection/timeout leaves the CLI's ordinary prompt available.
    data = object_value(raw)
    event = text(data.get("hook_event_name"), 64)
    if current.approval:
        behavior = "allow" if current.answers[0][1] == "Approve" else "deny"
        return {"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": {"behavior": behavior}}}
    answers = {current.questions[index].text: answer for index, answer in current.answers}
    if provider is Provider.CLAUDE:
        inputs = object_value(data.get("tool_input"))
        return {"hookSpecificOutput": {"hookEventName": event, "permissionDecision": "allow", "updatedInput": {**inputs, "answers": answers}}}
    # Codex has no documented hook result replacement. Skip the native question
    # and deliver the user's answer as the tool's model-visible blocking reason.
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": "The user answered this question through Workspace's inbox: " + json.dumps(answers, ensure_ascii=False),
        }
    }
