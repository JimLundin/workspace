"""The agent: a model working on a task with tools, step by step, until it's done,
stopped, or out of steps.

Every run executes one durable work claim. Requested work runs without approval
prompts by default, including self-updates; WORKSPACE_AGENT_APPROVALS=ask
requests a durable approval for each consequential action. The task profile's
toolset supplies the tool families and instructions; tool families own each
tool's facts, and the agent dispatches through `assistant.agent_tools`.
"""

import asyncio
import sqlite3
import threading
import time
import uuid
from collections.abc import Callable, Iterable
from dataclasses import replace
from typing import Final, Protocol

from pydantic import ConfigDict, TypeAdapter

from assistant import action_text
from assistant.activity import ContextSnapshot
from assistant.agent_history import History
from assistant.agent_tools import AdapterReadback, Args, ArgumentError, Display, Machine, Output, Tool, Verify
from assistant.desktop_tools import Screen
from assistant.llm import Settings, ToolCall
from assistant.publishing import PublishError
from assistant.workspace import SourceError
from automation.actions import ActionError, Change, Observation, Operation
from automation.execution import Log, Proof, Report, ReportStatus, Targets, WorkExecution
from automation.json_value import Json
from automation.presentation import Failed, Succeeded, ToolActivity, ToolStatus
from automation.task import FileDigest, NoVerification
from config import AGENT_MAX_STEPS
lazy from assistant import sdk

KEPT_SCREENSHOTS: Final = 2
"""Screenshots kept in the conversation; older ones are replaced by a note, to save space."""

_ARGUMENTS = TypeAdapter(dict[str, Json], config=ConfigDict(allow_inf_nan=False))


def registry(tools: Iterable[Tool]) -> frozendict[str, Tool]:
    """Every offered name has exactly one declaration."""
    named: dict[str, Tool] = {}
    for tool in tools:
        if tool.spec.name in named:
            raise ValueError(f"Two tool families declare {tool.spec.name}.")
        named[tool.spec.name] = tool
    return frozendict(named)


class Toolset(Protocol):
    """The tool families and instructions a task profile offers; the agent dispatches them without knowing which."""

    @property
    def tools(self) -> tuple[Tool, ...]: ...
    def instructions(self) -> str: ...


class Agent:
    __slots__ = (
        "after_step",
        "context",
        "context_image",
        "context_reader",
        "context_text",
        "history",
        "installing",
        "log",
        "machine",
        "max_steps",
        "report",
        "screen",
        "settings",
        "started",
        "stop",
        "timings",
        "tools",
        "toolset",
        "update",
        "work",
    )

    def __init__(
        self,
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
    ) -> None:
        # The agent composes its task profile's toolset over the machine, durable
        # work, history and starting context. Each varies independently.
        self.settings = settings
        self.machine = machine
        self.log = log
        self.update = log.updates()
        self.stop = stop
        self.max_steps = max_steps
        self.after_step = after_step
        self.history = history if history is not None else History()
        """Execution-owned volatile session IO; the SDK publishes immutable item bytes."""
        self.screen = Screen()
        self.started = 0.0
        self.timings: dict[str, float] = {}
        self.context, self.context_reader = context, context_reader
        self.context_text = ""
        self.context_image: bytes | None = None
        self.work = work
        self.report: Report = ReportStatus.STARTING
        self.installing: str | None = None
        """Set once the keeper has been asked to install: the task is over."""
        self.toolset = toolset(self)
        self.tools = registry(self.toolset.tools)

    def installation_requested(self, summary: str, /) -> None:
        self.installing = summary

    def current_context(self) -> ContextSnapshot | None:
        return self.context_reader() if self.context_reader is not None else self.context

    def run(self, task: str) -> bool:
        """Works on the task; True if the model said it was done."""
        self.started = time.monotonic()
        self.report = ReportStatus.STARTING
        if self.context is not None and self.context.state != "disabled" and not self.stop.is_set():
            self.context_text = self.context.describe()
            if work := self.context.window:
                try:
                    self.context_image, shot = self.machine.screenshot(handle=work.handle)
                    self.screen.capture(self.context_image, shot)
                    self.context_text += f"\nScreenshot captured now: {shot.width}x{shot.height}. {shot.area}"
                except OSError as error:
                    self.context_text += f"\nScreen context unavailable: {error}"
        prompt = self.toolset.instructions()
        prompt += (
            "\nApproval mode is enabled: tools handle the configured prompts; do not ask for the same approval in chat."
            if self.settings.agent_approvals
            else "\nApproval prompts are disabled. Execute authorized work directly; do not invent a confirmation step."
        )
        prompt += "\n\n" + self.work.instructions()
        return asyncio.run(sdk.run(self, task, prompt, tuple(tool.spec for tool in self.tools.values())))

    def mark(self, name: str) -> None:
        """Record the first occurrence of a stage, without recording conversation content."""
        self.timings.setdefault(name, round(time.monotonic() - self.started, 3))

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
        """Run a validated tool; its family describes each operation to approval and the durable boundary."""
        try:
            return tool.run(args)
        except (ArgumentError, SourceError, PublishError, ValueError) as error:
            return Output(f"Error: {error}", ok=False)
        except ActionError as error:
            self.work.block(str(error))
            return Output(f"Error: {error}", ok=False)
        except (OSError, sqlite3.Error) as error:
            try:
                if self.work.actions.unresolved():
                    self.work.block("An operation was interrupted without a conclusive outcome. Resume to inspect its result.")
            except OSError, sqlite3.Error:
                self.work.block("Durable storage is unavailable. Resume after it is available to inspect the result.")
            return Output(f"Error: {error}", ok=False)

    def effect(self, operation: Operation, perform: Callable[[], Output], verify: Verify = NoVerification.NONE) -> Output:
        """Its family classifies the exact operation; validation and approval happened before this."""
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
                    case AdapterReadback(target, confirm):
                        specification = change.specification(operation, target)
                        return self.work.actions.execute(specification, perform, lambda result: result.ok, self.stop, verify=confirm)
                    case _:
                        specification = change.specification(operation, NoVerification.NONE)
                        return self.work.actions.execute(specification, perform, lambda result: result.ok, self.stop, verify=verify)

    def approve(self, operation: Operation, title: str, detail: str) -> bool:
        """Prompt only in the user's opt-in approval mode; Stop always wins."""
        if self.stop.is_set():
            return False
        accepted = not self.settings.agent_approvals or self.work.approve(operation, title, detail)
        return accepted and not self.stop.is_set()

    def step(self, text: str, /) -> None:
        self.log.step(text)

    def proof(self, tool: str) -> Proof:
        """How a pending action's family lets an observation reconcile it."""
        declared = self.tools.get(tool)
        return declared.proof if declared is not None else Targets()
