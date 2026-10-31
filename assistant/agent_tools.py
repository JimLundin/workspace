"""The interface between the agent and its tool families.

A tool family owns each of its tools' facts in one declaration: the schema the
model sees, the handler, whether an operation reads or changes state and which
resources it holds, how its effect is proven, and what the visible log may show.
The agent dispatches and records through this interface; it never matches tool names.
"""

import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Final, Protocol

from pydantic import ConfigDict, TypeAdapter, ValidationError

from assistant.geometry import Shot
from assistant.llm import ToolSpec, tool_spec
from automation.actions import Classification, Operation
from automation.execution import Proof, Readback, Targets
from automation.json_value import Json
from automation.task import ActionNotApplied, ActionUncertain, ActionVerified, FileDigest, MailTarget, NoVerification
from winapi.shapes import Rect, Window
lazy from assistant.browser_requests import BrowserRequest
lazy from assistant.uia import UiRequest
lazy from assistant.web_apps import Located, WebAppOperation

_ARGUMENTS = TypeAdapter(dict[str, Json], config=ConfigDict(allow_inf_nan=False))

DECLINED: Final = "The user declined: don't run this. Ask them, or try something else."


class Machine(Protocol):
    """What the agent's tools act on: the computer."""

    def run_powershell(
        self,
        command: str,
        timeout_s: float,
        *,
        cwd: str | None = None,
        cancel: threading.Event | None = None,
    ) -> tuple[int, str]:
        """Exit code, and stdout and stderr together."""
        ...

    def screenshot(self, *, area: Rect | None = None, handle: int = 0, monitor: int = -1, longest: int = 1280) -> tuple[bytes, Shot]: ...
    def desktop_state(self) -> str: ...
    def window_action(self, handle: int, action: str, bounds: Rect | None = None) -> str: ...
    def inspect_ui(self, request: UiRequest, cancel: threading.Event) -> tuple[int, str]: ...
    def browse(self, request: BrowserRequest, cancel: threading.Event) -> tuple[str, bytes | None]: ...
    def web_app[Q: Located, R](self, operation: WebAppOperation[Q, R], query: Q, cancel: threading.Event) -> R:
        """A typed Teams, Outlook or Kanban operation in the signed-in browser."""
        ...

    def meeting(self, operation: str, source: str = "both", title: str = "Meeting") -> str: ...
    def move_mouse(self, x: int, y: int) -> None: ...
    def mouse_button(self, button: str, *, down: bool) -> None: ...
    def click(self, x: int, y: int, button: str, count: int) -> None:
        """At a point on the screen."""

    def type_text(self, text: str) -> None: ...
    def paste_text(self, text: str) -> None: ...
    def press_keys(self, strokes: list[tuple[int, bool]]) -> None:
        """Virtual keys going down (True) and up."""

    def scroll(self, x: int, y: int, clicks: int, *, horizontal: bool = False) -> None: ...
    def windows(self) -> list[Window]: ...
    def focus(self, handle: int) -> bool: ...
    def get_clipboard(self) -> str | None: ...
    def set_clipboard(self, text: str) -> None: ...
    def open(self, target: str) -> None:
        """A file, folder or web address, as double-clicking it would."""

    def install(self, summary: str) -> None:
        """Asks the keeper to install the workspace."""


@dataclass(frozen=True, slots=True)
class Output:
    text: str
    image: bytes | None = None
    ok: bool = field(default=True, kw_only=True)
    observation: str = field(default="", kw_only=True)
    """The recorded inspection's identifier, which only the model cites."""


class ArgumentError(Exception):
    pass


def rejected(tool: str, error: ValidationError) -> ArgumentError:
    """A tool seam's validation failure, phrased for the model by argument name."""
    problems = "; ".join(f"{'.'.join(str(part) for part in item['loc']) or 'arguments'}: {item['msg']}" for item in error.errors())
    return ArgumentError(f"{tool} arguments are invalid: {problems}.")


@dataclass(frozen=True, slots=True)
class Args:
    tool: str
    payload: bytes
    """Validated arguments remain immutable; effect adapters receive fresh wire values."""

    @property
    def values(self) -> dict[str, Json]:
        return _ARGUMENTS.validate_json(self.payload)

    @property
    def operation(self) -> Operation:
        """The operation exactly as requested; tools that resolve targets describe their own."""
        return Operation(self.tool, self.payload)


_SCHEMA: Final = TypeAdapter(dict[str, Json])


@dataclass(frozen=True, slots=True)
class NoArguments:
    """A tool that takes no arguments; any it is given are ignored."""


NO_ARGUMENTS: Final = TypeAdapter(NoArguments)


def argument_spec[A](name: str, description: str, arguments: TypeAdapter[A]) -> ToolSpec:
    """A tool's model schema, generated from the record its arguments validate into."""
    observed: object = arguments.json_schema()
    return tool_spec(name, description, _SCHEMA.validate_python(observed))


def typed_run[A](arguments: TypeAdapter[A], handler: Callable[[Args, A], Output]) -> Callable[[Args], Output]:
    """Validate a call's arguments into their record before the handler approves or acts."""

    def run(args: Args) -> Output:
        try:
            request = arguments.validate_json(args.payload)
        except ValidationError as error:
            raise rejected(args.tool, error) from error
        return handler(args, request)

    return run


def described[A](tool: str, arguments: TypeAdapter[A], record: A) -> Operation:
    """An operation a handler resolved itself, recorded from its typed record."""
    return Operation(tool, arguments.dump_json(record, exclude_none=True))


def typed_classification[A](
    arguments: TypeAdapter[A], classify: Callable[[A], Classification], fallback: Classification
) -> Callable[[Mapping[str, Json]], Classification]:
    """Targets come from the validated record; unparseable arguments keep only the tool's locks."""

    def classified(raw: Mapping[str, Json]) -> Classification:
        try:
            return classify(arguments.validate_json(_SCHEMA.dump_json(dict(raw))))
        except ValueError:
            return fallback

    return classified


type Verifier = Callable[[Output], ActionVerified | ActionUncertain | ActionNotApplied]


@dataclass(frozen=True, slots=True)
class AdapterReadback:
    """The adapter confirms its own result; a later run verifies the attempt by reading back `target` again."""

    target: MailTarget
    confirm: Verifier


type Verify = NoVerification | FileDigest | Verifier | AdapterReadback
"""A durable digest the journal checks, or the adapter's own confirmation of its result."""


class Session(Protocol):
    """What every tool family acts through: the computer, Stop, approval and durable effects."""

    @property
    def machine(self) -> Machine: ...
    @property
    def stop(self) -> threading.Event: ...
    def step(self, text: str, /) -> None:
        """Show the user a progress line."""
        ...

    def approve(self, operation: Operation, title: str, detail: str) -> bool:
        """Prompt only in the user's opt-in approval mode; Stop always wins."""
        ...

    def effect(self, operation: Operation, perform: Callable[[], Output], verify: Verify = NoVerification.NONE) -> Output:
        """Hold the operation's resources: record an inspection, or durably attempt a change."""
        ...


class Display(Enum):
    """What the visible tool log may show of a call."""

    PUBLIC = auto()
    PRIVATE = auto()
    """Integration content: neither arguments nor results are shown."""
    SUMMARY = auto()
    """Arguments are shown; the result is summarized as completed."""
    COMMAND = auto()
    """A longer command and its output are shown, including a failure's output."""


def no_readback(_arguments: Mapping[str, Json], _result: str) -> Readback:
    return Readback()


_EVERY_TARGET: Final = Targets()


@dataclass(frozen=True, slots=True)
class Tool:
    """One tool's complete facts; a declaration without a classification cannot be constructed."""

    spec: ToolSpec
    run: Callable[[Args], Output]
    classify: Callable[[Mapping[str, Json]], Classification]
    display: Display
    proof: Proof = _EVERY_TARGET
    readback: Callable[[Mapping[str, Json], str], Readback] = no_readback


def fixed(classification: Classification) -> Callable[[Mapping[str, Json]], Classification]:
    """A classification that no argument changes."""
    return lambda _arguments: classification


def schema(properties: Mapping[str, Json], required: Sequence[str]) -> dict[str, Json]:
    names: list[Json] = list(required)
    return {"type": "object", "properties": dict(properties), "required": names}


TEXT: Final[Json] = {"type": "string"}
NUMBER: Final[Json] = {"type": "integer"}
BOOL: Final[Json] = {"type": "boolean"}
