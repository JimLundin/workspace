"""The agent: a model working on a task with tools, step by step, until it's done,
stopped, or out of steps.

Every run executes one durable work claim; requested work, including
self-updates, runs without confirmation prompts. The task profile's
toolset supplies the tool families and instructions; tool families own each
tool's facts, and the agent dispatches through `assistant.agent_tools`.
"""

import asyncio
import sqlite3
import threading
import time
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from typing import Final, Protocol

from pydantic import ConfigDict, TypeAdapter

from assistant.agent_history import History
from assistant.agent_tools import Args, ArgumentError, Display, Machine, Output, Tool, Verify
from assistant.llm import Settings, ToolCall
from automation.actions import ActionError, Change, Observation, Operation, UncertainEffectError
from automation.activity import ContextSnapshot
from automation.execution import Log, Proof, Report, ReportStatus, Targets, WorkExecution
from cell import Cell
from config import AGENT_MAX_STEPS
from contracts import action_text
from contracts.json_value import Json
from contracts.presentation import Failed, LiveMessage, Succeeded, ToolActivity, ToolStatus
from contracts.task import FileDigest, NoVerification
lazy from assistant import sdk

KEPT_SCREENSHOTS: Final = 2
"""Screenshots kept in the conversation; older ones are replaced by a note, to save space."""

RECONCILE: Final = (
    "Use work_actions to find it, inspect its exact target from fresh state, then reconcile_action with that evidence. Do not repeat the effect."
)

_ARGUMENTS = TypeAdapter(dict[str, Json], config=ConfigDict(allow_inf_nan=False))


def registry(tools: Iterable[Tool]) -> frozendict[str, Tool]:
    """Every offered name has exactly one declaration."""
    offered = tuple(tools)
    names = tuple(tool.spec.name for tool in offered)
    first = {name: index for index, name in reversed(tuple(enumerate(names)))}
    repeated = next((name for index, name in enumerate(names) if first[name] != index), None)
    if repeated is not None:
        raise ValueError(f"Two tool families declare {repeated}.")
    return frozendict(zip(names, offered, strict=True))


class Toolset(Protocol):
    """The tool families and instructions a task profile offers; the agent dispatches them without knowing which."""

    @property
    def tools(self) -> tuple[Tool, ...]: ...
    def instructions(self) -> str: ...


@dataclass(frozen=True, slots=True)
class _Running:
    started: float = 0.0
    report: Report = ReportStatus.STARTING
    context_text: str = ""
    """The observed computer context sent with the request."""
    context_image: bytes | None = None
    timings: frozendict[str, float] = frozendict()
    """The first time each stage was reached, in seconds from the start."""


@dataclass(frozen=True, slots=True)
class _Tooling:
    toolset: Toolset
    tools: frozendict[str, Tool]


@dataclass(frozen=True, slots=True)
class Agent:
    # The agent composes its task profile's toolset over the machine, durable
    # work, history and starting context. Each varies independently.
    settings: Settings
    machine: Machine
    log: Log
    update: Callable[[LiveMessage], None]
    stop: threading.Event
    work: WorkExecution
    max_steps: int
    after_step: Callable[[], None] | None
    history: History
    """Execution-owned volatile session IO; the SDK publishes immutable item bytes."""
    context: ContextSnapshot | None
    context_reader: Callable[[], ContextSnapshot] | None
    _state: Cell[_Running] = field(default_factory=lambda: Cell(_Running()), init=False, repr=False)
    _tooling: Cell[_Tooling | None] = field(default_factory=lambda: Cell[_Tooling | None](None), init=False, repr=False)
    """The task profile's tools, built from this agent once it exists."""

    @classmethod
    def of(  # noqa: PLR0913 - injected collaborators and test seams
        cls,
        settings: Settings,
        machine: Machine,
        log: Log,
        stop: threading.Event,
        *,
        work: WorkExecution,
        toolset: Callable[[Agent], Toolset],
        max_steps: int = AGENT_MAX_STEPS,
        after_step: Callable[[], None] | None = None,
        history: History | None = None,
        context: ContextSnapshot | None = None,
        context_reader: Callable[[], ContextSnapshot] | None = None,
    ) -> Agent:
        held = history if history is not None else History()
        agent = cls(settings, machine, log, log.updates(), stop, work, max_steps, after_step, held, context, context_reader)
        built = toolset(agent)
        agent._tooling.set(_Tooling(built, registry(built.tools)))
        return agent

    def _tools(self) -> _Tooling:
        tooling = self._tooling.get()
        assert tooling is not None, "Agent.of builds the toolset before the agent is used."
        return tooling

    @property
    def toolset(self) -> Toolset:
        return self._tools().toolset

    @property
    def tools(self) -> frozendict[str, Tool]:
        return self._tools().tools

    @property
    def report(self) -> Report:
        return self._state.get().report

    @property
    def context_text(self) -> str:
        return self._state.get().context_text

    @property
    def context_image(self) -> bytes | None:
        return self._state.get().context_image

    @property
    def timings(self) -> frozendict[str, float]:
        return self._state.get().timings

    def reported(self, report: Report) -> None:
        """Record how the run ended, which decides the task's outcome."""
        self._state.set(replace(self._state.get(), report=report))

    def current_context(self) -> ContextSnapshot | None:
        return self.context_reader() if self.context_reader is not None else self.context

    def run(self, task: str) -> bool:
        """Works on the task; True if the model said it was done."""
        self._state.set(replace(self._state.get(), started=time.monotonic(), report=ReportStatus.STARTING))
        if self.context is not None and self.context.state != "disabled" and not self.stop.is_set():
            text = self.context.describe()
            image: bytes | None = None
            if work := self.context.window:
                try:
                    image, shot = self.machine.screenshot(handle=work.handle)
                    text += f"\nScreenshot captured now: {shot.width}x{shot.height}. {shot.area}"
                except OSError as error:
                    text += f"\nScreen context unavailable: {error}"
            self._state.set(replace(self._state.get(), context_text=text, context_image=image))
        prompt = self.toolset.instructions()
        prompt += "\nExecute authorized work directly; do not invent a confirmation step."
        prompt += "\n\n" + self.work.instructions()
        return asyncio.run(sdk.run(self, task, prompt, tuple(tool.spec for tool in self.tools.values())))

    def mark(self, name: str) -> None:
        """Record the first occurrence of a stage, without recording conversation content."""

        def marked(state: _Running) -> _Running:
            if name in state.timings:
                return state
            return replace(state, timings=frozendict({**state.timings, name: round(time.monotonic() - state.started, 3)}))

        self._state.update(marked)

    def call(self, call: ToolCall) -> Output:
        tool = self.tools.get(call.name)
        # A name no family declares shows nothing: it could carry integration content.
        display = tool.display if tool is not None else Display.PRIVATE
        command = display is Display.COMMAND
        private = display is Display.PRIVATE
        preview_limit = 2000 if command else 360
        detail = "" if private else action_text.arguments(call.name, call.arguments, limit=2000 if command else 240)
        started = time.time()
        identity = uuid.uuid4().hex
        self.update(ToolActivity(identity, call.name, detail, started))
        raw: dict[str, Json] | None
        try:
            raw = _ARGUMENTS.validate_json(call.arguments or "{}")
        except ValueError:
            raw = None
        if self.stop.is_set():
            output = Output("Stopped by the user.", ok=False)
        elif self.work.disposition is not None:
            output = Output("This task is waiting; this execution will suspend.", ok=False)
        elif raw is None:
            output = Output(f"Error: the arguments for {call.name} aren't a JSON object.", ok=False)
        elif tool is None:
            output = Output(f"Error: there's no tool called {call.name}.", ok=False)
        else:
            output = self.invoke(tool, Args(call.name, _ARGUMENTS.dump_json(raw)))
        preview = (
            "Completed."
            if display in (Display.PRIVATE, Display.SUMMARY)
            else action_text.result(call.name, output.text, limit=preview_limit)
            if output.ok or command
            else action_text.readable(output.text, limit=preview_limit)
        )
        outcome = Succeeded(preview) if output.ok else ToolStatus.CANCELLED if self.stop.is_set() else Failed("Failed." if private else preview)
        self.update(ToolActivity(identity, call.name, detail, started, outcome))
        self.log.step(call.name if private else f"{call.name} {call.arguments[:160]}" + ("" if output.ok else f"  ({output.text[:120]})"))
        # Only the model cites observation identifiers; the visible preview omits them.
        return replace(output, text=output.text + f"\n[observation_id: {output.observation}]") if output.observation else output

    def invoke(self, tool: Tool, args: Args) -> Output:
        """Run a validated tool; its family describes each operation to the durable boundary."""
        try:
            return tool.run(args)
        except (ArgumentError, ValueError) as error:
            return Output(f"Error: {error}", ok=False)
        except UncertainEffectError as error:
            # The journal still refuses every change until the uncertain action is
            # reconciled. Ending the task here left the model no turn to do that.
            return Output(f"Error: {error} {RECONCILE}", ok=False)
        except ActionError as error:
            self.work.block(str(error))
            return Output(f"Error: {error}", ok=False)
        except (OSError, sqlite3.Error) as error:
            try:
                if self.work.actions.unresolved():
                    return Output(f"Error: {error} The operation was interrupted without a conclusive outcome. {RECONCILE}", ok=False)
            except OSError, sqlite3.Error:
                self.work.block("Durable storage is unavailable. Resume after it is available to inspect the result.")
            return Output(f"Error: {error}", ok=False)

    def effect(self, operation: Operation, perform: Callable[[], Output], verify: Verify = NoVerification.NONE) -> Output:
        """Its family classifies the exact operation; validation happened before this."""
        tool = self.tools[operation.tool]
        match tool.classify(operation.arguments):
            case Observation() as observation:
                output = self.work.actions.execute(observation, perform, lambda result: result.ok, self.stop)
                if not output.ok:
                    return output
                readback = tool.readback(operation.arguments, output.text)
                return replace(output, observation=self.work.observed(operation.tool, observation, readback))
            case Change() as change:
                match verify:
                    case NoVerification() | FileDigest():
                        return self.work.actions.execute(change.specification(operation, verify), perform, lambda result: result.ok, self.stop)
                    case _:
                        specification = change.specification(operation, NoVerification.NONE)
                        return self.work.actions.execute(specification, perform, lambda result: result.ok, self.stop, verify=verify)

    def step(self, text: str, /) -> None:
        self.log.step(text)

    def proof(self, tool: str) -> Proof:
        """How a pending action's family lets an observation reconcile it."""
        declared = self.tools.get(tool)
        return declared.proof if declared is not None else Targets()
