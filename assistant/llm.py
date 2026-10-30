"""The AI endpoint: settings, transcription, and chat (plain, streamed, with tools
and images), against any OpenAI-style API. Pydantic validates incoming JSON.
Every call returns its result or a `Failure`; none
raise for network or server problems."""

import base64
import io
import urllib.error
import urllib.request
import uuid
import wave
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from http.client import HTTPException, HTTPResponse
from typing import Final, Literal, NotRequired, TypedDict, assert_never

from pydantic import ConfigDict, TypeAdapter

RATE: Final = 16_000
"""Samples per second. Speech models work at 16 kHz; more only makes uploads bigger."""
MAX_SECONDS: Final = 300
"""Longest recording; the buffer for it (9.6 MB) is allocated once, at start."""
MIN_SECONDS: Final = 0.3
"""Shorter recordings are accidental taps, and aren't sent."""

type Json = str | int | float | bool | list[Json] | dict[str, Json] | None

_JSON = TypeAdapter(Json)
_SCHEMA = TypeAdapter(dict[str, Json], config=ConfigDict(allow_inf_nan=False))


# ---- Settings --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Settings:
    base_url: str
    """The endpoint's base, as OpenAI's own libraries take it: `https://.../v1`."""
    api_key: str
    transcribe_model: str
    chat_model: str
    """For quick jobs: tidying dictation, rewrites, questions, screenshots."""
    agent_model: str
    vocabulary: str
    """Names and terms to expect when transcribing; helps with jargon. Empty: none."""
    language: str
    """An ISO code such as `sv` or `en` for transcription. Empty: detected."""
    agent_reasoning_effort: str = "low"
    """Reasoning effort for agent tasks; independent of quick chat."""
    agent_approvals: bool = field(default=False, kw_only=True)
    """Opt in to tool and self-update approval prompts."""


@dataclass(frozen=True, slots=True)
class Missing:
    """Required environment variables that aren't set."""

    names: tuple[str, ...]


def settings_from(env: Mapping[str, str]) -> Settings | Missing:
    """Read from environment variables. The endpoint's are named as OpenAI's own tools name them."""
    required = ("OPENAI_BASE_URL", "OPENAI_API_KEY")
    if missing := tuple(name for name in required if not env.get(name)):
        return Missing(missing)
    chat_model = env.get("WORKSPACE_CHAT_MODEL", "gpt-5.4-mini")
    return Settings(
        base_url=env["OPENAI_BASE_URL"].rstrip("/"),
        api_key=env["OPENAI_API_KEY"],
        transcribe_model=env.get("WORKSPACE_TRANSCRIBE_MODEL", "gpt-4o-transcribe"),
        chat_model=chat_model,
        agent_model=env.get("WORKSPACE_AGENT_MODEL", "gpt-6.1-sol"),
        vocabulary=env.get("WORKSPACE_VOCABULARY", ""),
        language=env.get("WORKSPACE_LANGUAGE", ""),
        agent_reasoning_effort=env.get("WORKSPACE_AGENT_REASONING_EFFORT", "low"),
        agent_approvals=env.get("WORKSPACE_AGENT_APPROVALS", "never").lower() == "ask",
    )


# ---- Audio -----------------------------------------------------------------------------


def long_enough(pcm: bytes) -> bool:
    """16-bit mono at `RATE`: two bytes per sample."""
    return len(pcm) >= 2 * RATE * MIN_SECONDS


def wav(pcm: bytes, rate: int) -> bytes:
    """16-bit mono PCM as a WAV file."""
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return out.getvalue()


# ---- Messages --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Text:
    text: str


@dataclass(frozen=True, slots=True)
class Image:
    png: bytes


type Part = Text | Image


@dataclass(frozen=True, slots=True)
class ToolCall:
    id: str
    name: str
    arguments: str
    """JSON, as the model wrote it (it may not be valid)."""


@dataclass(frozen=True, slots=True)
class SystemMessage:
    text: str


@dataclass(frozen=True, slots=True)
class UserMessage:
    content: str | tuple[Part, ...]


@dataclass(frozen=True, slots=True)
class AssistantMessage:
    text: str
    tool_calls: tuple[ToolCall, ...] = ()


@dataclass(frozen=True, slots=True)
class ToolResult:
    call_id: str
    text: str


type Message = SystemMessage | UserMessage | AssistantMessage | ToolResult


def system_message(text: str) -> SystemMessage:
    return SystemMessage(text)


def user_message(content: str | Sequence[Part]) -> UserMessage:
    return UserMessage(content if isinstance(content, str) else tuple(content))


def assistant_message(text: str, tool_calls: tuple[ToolCall, ...] = ()) -> AssistantMessage:
    return AssistantMessage(text, tool_calls)


def tool_result(call_id: str, text: str) -> ToolResult:
    return ToolResult(call_id, text)


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """A function the model may call."""

    name: str
    description: str
    parameters: bytes
    """Validated schema wire bytes; adapters parse their own fresh SDK/HTTP values."""


def tool_spec(name: str, description: str, parameters: Mapping[str, Json]) -> ToolSpec:
    """Snapshot a tool schema at its declaration boundary without retaining aliases."""
    schema = _SCHEMA.validate_python(parameters)
    return ToolSpec(name, description, _SCHEMA.dump_json(schema))


@dataclass(frozen=True, slots=True)
class Reply:
    text: str
    tool_calls: tuple[ToolCall, ...]


@dataclass(frozen=True, slots=True)
class Failure:
    message: str


@dataclass(frozen=True, slots=True)
class CompletionRequest:
    """One immutable chat exchange: messages, model, tools and response mode."""

    messages: tuple[Message, ...]
    model: str | None = None
    tools: tuple[ToolSpec, ...] = ()
    streaming: bool = field(default=False, kw_only=True)


class WireText(TypedDict):
    type: Literal["text"]
    text: str


class ImageLocation(TypedDict):
    url: str


class WireImage(TypedDict):
    type: Literal["image_url"]
    image_url: ImageLocation


type WirePart = WireText | WireImage


class WireCallFunction(TypedDict):
    name: str
    arguments: str


class WireCall(TypedDict):
    id: str
    type: Literal["function"]
    function: WireCallFunction


class WireSystem(TypedDict):
    role: Literal["system"]
    content: str


class WireUser(TypedDict):
    role: Literal["user"]
    content: str | tuple[WirePart, ...]


class WireAssistant(TypedDict):
    role: Literal["assistant"]
    content: str | None
    tool_calls: NotRequired[tuple[WireCall, ...]]


class WireResult(TypedDict):
    role: Literal["tool"]
    tool_call_id: str
    content: str


type WireMessage = WireSystem | WireUser | WireAssistant | WireResult


class WireFunction(TypedDict):
    name: str
    description: str
    parameters: dict[str, Json]


class WireTool(TypedDict):
    type: Literal["function"]
    function: WireFunction


class WireCompletion(TypedDict):
    model: str
    messages: tuple[WireMessage, ...]
    tools: NotRequired[tuple[WireTool, ...]]
    stream: NotRequired[Literal[True]]


_COMPLETION = TypeAdapter(WireCompletion)


def _part(part: Part) -> WirePart:
    match part:
        case Text(text):
            return {"type": "text", "text": text}
        case Image(png):
            return {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{base64.b64encode(png).decode()}"}}
        case _:
            assert_never(part)


def _call(call: ToolCall) -> WireCall:
    return {"id": call.id, "type": "function", "function": {"name": call.name, "arguments": call.arguments}}


def _message(message: Message) -> WireMessage:
    match message:
        case SystemMessage(text):
            return {"role": "system", "content": text}
        case UserMessage(content):
            return {"role": "user", "content": content if isinstance(content, str) else tuple(_part(part) for part in content)}
        case AssistantMessage(text, calls):
            out: WireAssistant = {"role": "assistant", "content": text}
            if calls:
                out["content"] = text or None
                out["tool_calls"] = tuple(_call(call) for call in calls)
            return out
        case ToolResult(call_id, text):
            return {"role": "tool", "tool_call_id": call_id, "content": text}
        case _:
            assert_never(message)


def _tool(spec: ToolSpec) -> WireTool:
    return {
        "type": "function",
        "function": {"name": spec.name, "description": spec.description, "parameters": _SCHEMA.validate_json(spec.parameters)},
    }


# ---- Reading JSON replies --------------------------------------------------------------


def _json(body: bytes) -> Json:
    try:
        return _JSON.validate_json(body)
    except ValueError:
        return None


def _get(data: Json, *path: str | int) -> Json:
    """`data[a][b]...`, or None where the path doesn't exist."""
    for step in path:
        match step, data:
            case str() as key, dict() as values:
                data = values.get(key)
            case int() as index, list() as values if -len(values) <= index < len(values):
                data = values[index]
            case _:
                return None
    return data


def _str(data: Json, *path: str | int) -> str:
    value = _get(data, *path)
    return value if isinstance(value, str) else ""


def _items(data: Json) -> list[Json]:
    return data if isinstance(data, list) else []


def _unexpected(body: bytes) -> Failure:
    return Failure(f"unexpected reply: {body[:200].decode(errors='replace')}")


# ---- Requests --------------------------------------------------------------------------


def _request(settings: Settings, path: str, body: bytes, content_type: str) -> urllib.request.Request:
    return urllib.request.Request(
        f"{settings.base_url}{path}",
        data=body,
        headers={"Authorization": f"Bearer {settings.api_key}", "Content-Type": content_type},
        method="POST",
    )


def _open(request: urllib.request.Request, timeout_s: float) -> HTTPResponse | Failure:
    """Goes through the system's proxy settings, and trusts the certificates the
    system trusts (so company TLS inspection works)."""
    try:
        response: object = urllib.request.urlopen(request, timeout=timeout_s)
    except urllib.error.HTTPError as error:
        try:
            with error:
                detail = _get(_json(error.read()), "error", "message")
        except OSError, HTTPException:
            detail = None
        return Failure(f"HTTP {error.code}: {detail if isinstance(detail, str) else error.reason}")
    except urllib.error.URLError as error:
        return Failure(f"can't reach {request.host}: {error.reason}")
    except (OSError, HTTPException) as error:  # timeouts, truncated replies and dropped connections
        return Failure(f"can't reach {request.host}: {error}")
    match response:
        case HTTPResponse():
            return response
        case _:
            return Failure("unexpected HTTP response")


def _post(request: urllib.request.Request, timeout_s: float) -> bytes | Failure:
    response = _open(request, timeout_s)
    if isinstance(response, Failure):
        return response
    try:
        with response:
            return response.read()
    except (OSError, HTTPException) as error:
        return Failure(f"connection dropped: {error}")


def _multipart(fields: Mapping[str, str], audio: bytes) -> tuple[bytes, str]:
    """A multipart/form-data body with text fields and the audio file; and its content type."""
    boundary = uuid.uuid4().hex
    parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode() for name, value in fields.items()]
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="speech.wav"\r\nContent-Type: audio/wav\r\n\r\n'.encode())
    parts.append(audio + f"\r\n--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def transcribe(settings: Settings, audio: bytes, *, timeout_s: float = 60, context: str = "") -> str | Failure:
    """The text spoken in a WAV file."""
    fields = {"model": settings.transcribe_model, "response_format": "json"}
    prompt = "\n".join(part for part in (settings.vocabulary, context[-600:]) if part)
    if prompt:
        fields["prompt"] = prompt
    if settings.language:
        fields["language"] = settings.language
    body, content_type = _multipart(fields, audio)
    reply = _post(_request(settings, "/audio/transcriptions", body, content_type), timeout_s)
    if isinstance(reply, Failure):
        return reply
    text = _get(_json(reply), "text")
    return text if isinstance(text, str) else _unexpected(reply)


def _chat_body(settings: Settings, request: CompletionRequest) -> bytes:
    body: WireCompletion = {"model": request.model or settings.chat_model, "messages": tuple(_message(message) for message in request.messages)}
    if request.tools:
        body["tools"] = tuple(_tool(tool) for tool in request.tools)
    if request.streaming:
        body["stream"] = True
    return _COMPLETION.dump_json(body)


def chat(
    settings: Settings,
    messages: Sequence[Message],
    *,
    model: str | None = None,
    tools: Sequence[ToolSpec] = (),
    timeout_s: float = 120,
) -> Reply | Failure:
    """The model's answer: text, or calls to the tools it was offered."""
    body = _chat_body(settings, CompletionRequest(tuple(messages), model, tuple(tools)))
    reply = _post(_request(settings, "/chat/completions", body, "application/json"), timeout_s)
    if isinstance(reply, Failure):
        return reply
    message = _get(_json(reply), "choices", 0, "message")
    if _get(message, "role") is None and _get(message, "content") is None:
        return _unexpected(reply)
    calls = tuple(ToolCall(_str(c, "id"), _str(c, "function", "name"), _str(c, "function", "arguments")) for c in _items(_get(message, "tool_calls")))
    return Reply(_str(message, "content"), calls)


def _events(response: HTTPResponse) -> Iterator[Json]:
    """The JSON payloads of a server-sent event stream, up to `[DONE]`."""
    for raw in response:
        line = raw.decode("utf-8", errors="replace").strip()
        if not line.startswith("data:"):
            continue
        data = line.removeprefix("data:").strip()
        if data == "[DONE]":
            return
        yield _json(data.encode())


def stream(
    settings: Settings,
    messages: Sequence[Message],
    on_text: Callable[[str], object],
    *,
    model: str | None = None,
    timeout_s: float = 120,
) -> str | Failure:
    """The model's answer, passed to `on_text` piece by piece as it's written; all of it at the end."""
    body = _chat_body(settings, CompletionRequest(tuple(messages), model, streaming=True))
    response = _open(_request(settings, "/chat/completions", body, "application/json"), timeout_s)
    if isinstance(response, Failure):
        return response
    pieces: list[str] = []
    try:
        with response:
            for event in _events(response):
                if piece := _str(event, "choices", 0, "delta", "content"):
                    pieces.append(piece)
                    on_text(piece)
    except (OSError, HTTPException) as error:
        return Failure(f"connection dropped: {error}")
    return "".join(pieces)


def ask(settings: Settings, instructions: str, content: str | Sequence[Part], *, model: str | None = None) -> str | Failure:
    """One question, one answer."""
    reply = chat(settings, [system_message(instructions), user_message(content)], model=model)
    return reply if isinstance(reply, Failure) else reply.text
