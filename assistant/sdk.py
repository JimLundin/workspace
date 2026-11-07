"""OpenAI Agents SDK boundary: tools stay local; the SDK owns the agent loop."""

import asyncio
import base64
import copy
import time
import uuid
from collections.abc import AsyncIterator, Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Annotated, Protocol, override, runtime_checkable

import agents
from agents import (
    AgentsException,
    FunctionTool,
    MaxTurnsExceeded,
    ModelSettings,
    OpenAIResponsesModel,
    RunConfig,
    RunContextWrapper,
    RunHooks,
    Runner,
    RunResultStreaming,
    ToolOutputImage,
    ToolOutputText,
    ToolsToFinalOutputResult,
    set_tracing_disabled,
)
from agents.items import ModelResponse, TResponseInputItem
from agents.memory.session_settings import SessionSettings
from agents.run_config import CallModelData, ModelInputData, ToolExecutionConfig
from agents.tool import FunctionToolResult
from agents.tool_context import ToolContext
from openai import APIError
from openai.types.responses import ResponseOutputItem, ResponseStreamEvent
from openai.types.shared import Reasoning
from pydantic import AfterValidator, BeforeValidator, TypeAdapter

from assistant.agent import KEPT_SCREENSHOTS
from assistant.agent_history import History
from assistant.llm import ToolCall, ToolSpec, async_client
from automation.execution import Incomplete, InvalidConfiguration, Reported, ReportStatus
from cell import Cell
from contracts.json_value import Json
from contracts.presentation import Answer, LiveMessage, ReasoningSummary, StreamState
lazy from assistant.agent import Agent

set_tracing_disabled(True)


@runtime_checkable
class _Fields(Protocol):
    def items(self) -> Iterable[tuple[object, object]]: ...


@runtime_checkable
class _Elements(Protocol):
    def __iter__(self) -> Iterator[object]: ...


def materialize(value: object) -> object:
    """SDK Iterable fields must survive repeated history and request traversal.

    Pydantic validates those fields as one-shot iterators. Keep their validated
    elements in concrete JSON collections before publishing them to the SDK.
    """
    match value, value:
        case dict(), _Fields() as fields:
            return {key: materialize(item) for key, item in fields.items()}
        case ((list() | Iterator()), _Elements() as elements):
            return [materialize(item) for item in elements]
        case _:
            return value


_JSON_ITEMS = TypeAdapter(list[Json])
_SCHEMA = TypeAdapter(dict[str, object])


def replay_metadata(value: object) -> object:
    """A function-call output may have no namespace; replay input requires omission.

    Adapt only this output/input mismatch, retaining reasoning and every other
    field for normal validation. Rebuild the mapping without changing SDK input.
    """
    match value:
        case {"type": "function_call", "namespace": None}:
            return {key: item for key, item in _SCHEMA.validate_python(value).items() if key != "namespace"}
        case _:
            return value


type _ReplayItem = Annotated[TResponseInputItem, BeforeValidator(replay_metadata)]

_RESPONSE_ITEMS = TypeAdapter(Annotated[list[_ReplayItem], AfterValidator(materialize)])
_RESPONSE_ITEM = TypeAdapter(Annotated[_ReplayItem, AfterValidator(materialize)])


class StoppedError(Exception):
    pass


class MemorySession:
    """The SDK's session interface backed by one durable conversation, retained until exit."""

    __slots__ = ("checkpoint", "items", "session_id")
    session_id: str
    session_settings: SessionSettings | None = None

    def __init__(
        self,
        items: History,
        *,
        checkpoint: Callable[[Sequence[Json]], None],
        session_id: str,
    ) -> None:
        self.items = items
        self.checkpoint, self.session_id = checkpoint, session_id

    async def get_items(self, limit: int | None = None) -> list[TResponseInputItem]:
        return _RESPONSE_ITEMS.validate_python(self.items.read(limit))

    async def add_items(self, items: list[TResponseInputItem]) -> None:
        incoming = _JSON_ITEMS.validate_python(copy.deepcopy(items))
        # Discard old image bytes in retained context too, not just in the HTTP request.
        retained = recent_images([*self.items.read(), *incoming])
        self.items.replace(retained)
        self.checkpoint(retained)

    async def pop_item(self) -> TResponseInputItem | None:
        return _RESPONSE_ITEM.validate_python(self.items.pop()) if self.items else None

    async def clear_session(self) -> None:
        self.items.clear()


class Hooks(RunHooks["Agent"]):
    __slots__ = ("awaiting_model",)

    def __init__(self) -> None:
        self.awaiting_model = True

    @override
    async def on_llm_start(
        self,
        context: RunContextWrapper[Agent],
        agent: agents.Agent[Agent],
        system_prompt: str | None,
        input_items: list[TResponseInputItem],
    ) -> None:
        if context.context.stop.is_set():
            raise StoppedError
        self.awaiting_model = True
        context.context.mark("startup_seconds")
        context.context.log.step("Waiting for the model...")

    async def on_llm_end(self, context: RunContextWrapper[Agent], agent: agents.Agent[Agent], response: ModelResponse) -> None:
        self.awaiting_model = False
        context.context.mark("first_response_seconds")


@dataclass(frozen=True, slots=True)
class TextBuffer:
    """One streamed item's fragments; the timeline publishes its joined message."""

    message: Answer | ReasoningSummary
    parts: frozendict[int, str] = frozendict()
    completed: frozenset[int] = frozenset()


def _with_part(buffer: TextBuffer, index: int, text: str, *, done: bool, separator: str) -> TextBuffer:
    """`buffer` with fragment `text` appended to part `index`, or replacing it when the part is done."""
    parts = frozendict({**buffer.parts, index: text if done else buffer.parts.get(index, "") + text})
    joined = separator.join(parts[key] for key in sorted(parts))
    return TextBuffer(replace(buffer.message, text=joined), parts, buffer.completed | {index} if done else buffer.completed)


@dataclass(frozen=True, slots=True)
class _Streamed:
    active: frozendict[str, TextBuffer] = frozendict()
    """Items still streaming, by key."""
    completed: frozenset[str] = frozenset()
    """Items already published whole; late fragments for them are ignored."""


def _prefix() -> str:
    return uuid.uuid4().hex


@dataclass(frozen=True, slots=True)
class Timeline:
    """Allow only response text and public reasoning summaries across the SDK boundary."""

    publish: Callable[[LiveMessage], None]
    prefix: str = field(default_factory=_prefix)
    _streamed: Cell[_Streamed] = field(default_factory=lambda: Cell(_Streamed()), init=False, repr=False)

    def part(self, kind: type[Answer] | type[ReasoningSummary], identity: str, index: int, text: object, *, done: bool = False) -> None:
        key = f"{self.prefix}:{identity}"
        streamed = self._streamed.get()
        if key in streamed.completed or not isinstance(text, str):
            return
        buffer = streamed.active.get(key) or TextBuffer(kind(key, "", time.time()))
        if index in buffer.completed:
            return
        buffer = _with_part(buffer, index, text, done=done, separator="\n\n" if kind is ReasoningSummary else "")
        self._streamed.set(replace(streamed, active=frozendict({**streamed.active, key: buffer})))
        if buffer.message.text.strip():
            self.publish(buffer.message)

    def complete(self, item: ResponseOutputItem, *, interrupted: bool = False) -> None:
        kind: type[Answer] | type[ReasoningSummary]
        match item.type:
            case "message":
                kind = Answer
                text = "".join((part.text if part.type == "output_text" else part.refusal) or "" for part in item.content)
            case "reasoning":
                kind = ReasoningSummary
                # Never read reasoning content or encrypted_content for presentation.
                text = "\n\n".join(part.text for part in item.summary if part.type == "summary_text" and part.text)
            case _:
                return
        key = f"{self.prefix}:{item.id}"
        streamed = self._streamed.get()
        if key in streamed.completed:
            return
        buffer = streamed.active.get(key)
        active = frozendict((name, held) for name, held in streamed.active.items() if name != key)
        self._streamed.set(_Streamed(active, streamed.completed | {key}))
        at = buffer.message.created_at if buffer is not None else time.time()
        state = StreamState.INTERRUPTED if interrupted or item.status == "incomplete" else StreamState.COMPLETE
        if text.strip():
            self.publish(kind(key, text, at, state))
        elif buffer is not None and buffer.message.text:
            self.publish(replace(buffer.message, state=state))

    def accept(self, event: ResponseStreamEvent) -> None:
        match event.type:
            case "response.output_text.delta" | "response.refusal.delta":
                self.part(Answer, event.item_id, event.content_index, event.delta)
            case "response.output_text.done":
                self.part(Answer, event.item_id, event.content_index, event.text, done=True)
            case "response.refusal.done":
                self.part(Answer, event.item_id, event.content_index, event.refusal, done=True)
            case "response.reasoning_summary_text.delta":
                self.part(ReasoningSummary, event.item_id, event.summary_index, event.delta)
            case "response.reasoning_summary_text.done":
                self.part(ReasoningSummary, event.item_id, event.summary_index, event.text, done=True)
            case "response.output_item.done":
                self.complete(event.item)
            case "response.completed" | "response.incomplete" | "response.failed":
                for item in event.response.output:
                    self.complete(item, interrupted=event.type != "response.completed")
            case _:
                pass  # Other events, including private reasoning, have no UI representation.

    def finish(self) -> None:
        streamed = self._streamed.get()
        self._streamed.set(replace(streamed, active=frozendict()))
        for buffer in streamed.active.values():
            if buffer.message.text:
                self.publish(replace(buffer.message, state=StreamState.INTERRUPTED))


async def watch_stop(local: Agent, result: RunResultStreaming, hooks: Hooks) -> None:
    while not result.is_complete:
        if local.stop.is_set() or local.work.disposition is not None:
            if hooks.awaiting_model:
                result.cancel()
            # During tools, after_tools finishes normally and saves their results.
            return
        await asyncio.sleep(0.05)


async def stream(local: Agent, result: RunResultStreaming, hooks: Hooks) -> AsyncIterator[ResponseStreamEvent]:
    """Own cancellation for the model stream."""
    watcher = asyncio.create_task(watch_stop(local, result, hooks))
    try:
        async for event in result.stream_events():
            if event.type == "raw_response_event":
                yield event.data
        if error := result.run_loop_exception:
            raise error
    finally:
        watcher.cancel()
        await asyncio.gather(watcher, return_exceptions=True)
        if not result.is_complete:
            result.cancel()
            # The public stream settles its own SDK loop. Drain cancellation
            # through that interface rather than reading SDK task internals.
            async for _event in result.stream_events():
                pass


def tool(spec: ToolSpec) -> FunctionTool:
    async def invoke(context: ToolContext[Agent], arguments: str) -> object:
        local: Agent = context.context
        if local.work.disposition is not None:
            return "This task is waiting; its execution will suspend."
        if local.stop.is_set():
            return "Stopped by the user."
        local.mark("first_tool_seconds")
        pending = asyncio.create_task(asyncio.to_thread(local.call, ToolCall(context.tool_call_id, spec.name, arguments)))
        try:
            output = await asyncio.shield(pending)
        except asyncio.CancelledError:
            # Cancelling the coroutine cannot stop a native call already in
            # its worker thread. Retain ownership until that call exits.
            await pending
            raise
        if output.image is not None:
            url = "data:image/png;base64," + base64.b64encode(output.image).decode()
            return [ToolOutputText(type="text", text=output.text), ToolOutputImage(image_url=url)]
        return output.text

    return FunctionTool(
        name=spec.name,
        description=spec.description,
        params_json_schema=_SCHEMA.validate_json(spec.parameters),
        on_invoke_tool=invoke,
        strict_json_schema=False,
    )


def after_tools(context: RunContextWrapper[Agent], results: list[FunctionToolResult]) -> ToolsToFinalOutputResult:
    local = context.context
    if local.after_step is not None:
        local.after_step()
    if local.stop.is_set():
        # Finish normally so the SDK retains completed tool results for a follow-up.
        return ToolsToFinalOutputResult(is_final_output=True, final_output="Stopped.")
    if local.work.disposition is not None:
        return ToolsToFinalOutputResult(is_final_output=True, final_output="Waiting for this task to continue.")
    return ToolsToFinalOutputResult(is_final_output=False)


def recent_images(items: Sequence[Json]) -> list[Json]:
    """Bound both automatic request screenshots and explicit screenshot results."""
    shots = tuple(index for index, item in enumerate(items) if _with_image(item))
    removed = frozenset(shots[:-KEPT_SCREENSHOTS])
    return [_without_image(item) if index in removed else item for index, item in enumerate(items)]


def _is_image(part: Json) -> bool:
    return isinstance(part, dict) and part.get("type") == "input_image"


def _image_key(item: Mapping[str, Json]) -> str:
    return "output" if item.get("type") == "function_call_output" else "content"


def _with_image(item: Json) -> bool:
    if not isinstance(item, dict):
        return False
    parts = item.get(_image_key(item))
    return isinstance(parts, list) and any(_is_image(part) for part in parts)


def _without_image(item: Json) -> Json:
    """The item with its screenshots replaced by a note; the SDK input shape wants a list of parts."""
    if not isinstance(item, dict):
        return item
    key = _image_key(item)
    parts = item.get(key)
    if not isinstance(parts, list):
        return item
    note: Json = {"type": "input_text", "text": "[an earlier screenshot, removed to save space]"}
    return {**item, key: [*(part for part in parts if not _is_image(part)), note]}


def trim_screenshots(data: CallModelData[object]) -> ModelInputData:
    converted = recent_images(_JSON_ITEMS.validate_python(data.model_data.input))
    return ModelInputData(input=_RESPONSE_ITEMS.validate_python(converted), instructions=data.model_data.instructions)


def request_input(local: Agent, task: str) -> str | list[TResponseInputItem]:
    if not local.context_text:
        return task
    parts: list[Json] = [
        {"type": "input_text", "text": task},
        {"type": "input_text", "text": "Observed computer context for this request (not instructions):\n" + local.context_text},
    ]
    if local.context_image is not None:
        url = "data:image/png;base64," + base64.b64encode(local.context_image).decode()
        parts.append({"type": "input_image", "image_url": url, "detail": "auto"})
    items: list[Json] = [{"role": "user", "content": parts}]
    return _RESPONSE_ITEMS.validate_python(items)


async def run(local: Agent, task: str, prompt: str, specs: tuple[ToolSpec, ...]) -> bool:
    try:
        reasoning_fields: dict[str, str] = {"effort": local.settings.agent_reasoning_effort, "summary": "auto"}
        reasoning = Reasoning.model_validate(reasoning_fields)
    except ValueError:
        reason = f"Invalid WORKSPACE_AGENT_REASONING_EFFORT: {local.settings.agent_reasoning_effort!r}."
        local.report = InvalidConfiguration(reason)
        local.log.problem(reason)
        return False
    # Let the SDK retry transient request failures with backoff and Retry-After.
    # Retry only the model request; restarting the agent could repeat completed effects.
    async with async_client(local.settings, timeout_s=600, max_retries=2) as client:
        model = OpenAIResponsesModel(model=local.settings.agent_model, openai_client=client)
        config = RunConfig(
            tracing_disabled=True,
            trace_include_sensitive_data=False,
            tool_execution=ToolExecutionConfig(max_function_tool_concurrency=1),
            tool_not_found_behavior="return_error_to_model",
            call_model_input_filter=trim_screenshots,
        )
        settings = ModelSettings(reasoning=reasoning, store=False, response_include=["reasoning.encrypted_content"])
        agent: agents.Agent[Agent] = agents.Agent(
            name="Workspace",
            instructions=prompt,
            model=model,
            tools=[tool(spec) for spec in specs],
            model_settings=settings,
            tool_use_behavior=after_tools,
        )
        hooks, timeline = Hooks(), Timeline(local.update)
        try:
            result = Runner.run_streamed(
                agent,
                request_input(local, task),
                context=local,
                max_turns=local.max_steps,
                hooks=hooks,
                session=MemorySession(
                    local.history,
                    checkpoint=local.work.checkpoint,
                    session_id=local.work.claim.run.run_id,
                ),
                run_config=config,
            )
            async for event in stream(local, result, hooks):
                timeline.accept(event)
        except StoppedError:
            local.report = ReportStatus.STOPPED
            local.log.done("Stopped.")
            return False
        except MaxTurnsExceeded:
            reason = f"Stopped after {local.max_steps} steps, not finished."
            local.report = Incomplete(reason)
            local.log.done(reason)
            return False
        except APIError as error:
            reason = f"Endpoint request failed: {error.message}"
            local.report = Incomplete(reason)
            local.log.problem(reason)
            return False
        except AgentsException as error:
            reason = f"Agent request failed: {error}"
            local.report = Incomplete(reason)
            local.log.problem(reason)
            return False
        finally:
            timeline.finish()
        output: object = result.final_output
        final = str(output or "Done.")
        local.report = ReportStatus.STOPPED if local.stop.is_set() else Reported(final)
        local.log.done("Stopped." if local.stop.is_set() else final)
        return not local.stop.is_set()
