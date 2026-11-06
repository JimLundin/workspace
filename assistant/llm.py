"""The AI endpoint: settings, the SDK clients and transcription,
against any OpenAI-style API. Pydantic validates the replies we read.
`transcribe` returns its result or a `Failure`; it doesn't raise for
network or server problems."""

import io
import wave
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypedDict, assert_never
from urllib.parse import urlsplit

from pydantic import ConfigDict, TypeAdapter, ValidationError
lazy from openai import APIConnectionError, APIStatusError, AsyncOpenAI, OpenAI, omit

from automation.json_value import Json
from gateway.endpoint import read
from winapi.pcm import RATE

MAX_SECONDS: Final = 300
"""Longest recording; the buffer for it (9.6 MB) is allocated once, at start."""
MIN_SECONDS: Final = 0.3
"""Shorter recordings are accidental taps, and aren't sent."""

_SCHEMA = TypeAdapter(dict[str, Json], config=ConfigDict(allow_inf_nan=False))


# ---- Settings --------------------------------------------------------------------------

FAST_MODEL: Final = "gpt-6-luna"
AGENT_MODEL: Final = "gpt-6-astra"


@dataclass(frozen=True, slots=True)
class Settings:
    base_url: str
    """The endpoint's base, as OpenAI's own libraries take it: `https://.../v1`."""
    api_key: str
    transcribe_model: str
    vocabulary: str
    """Names and terms to expect when transcribing; helps with jargon. Empty: none."""
    fast_model: str = FAST_MODEL
    """Quick jobs: tidying dictation and screening notifications."""
    agent_model: str = AGENT_MODEL
    """The agent and every other model job."""
    agent_reasoning_effort: str = "low"
    """Reasoning effort for agent tasks; independent of the fast model."""
    gateway: Path | None = None
    """Where the AI connection publishes its endpoint; requests go through it once it
    has. None calls `base_url` directly."""

    def __post_init__(self) -> None:
        if not self.fast_model.strip() or not self.agent_model.strip():
            raise ValueError("Model IDs must not be empty.")


@dataclass(frozen=True, slots=True)
class Missing:
    """Required environment variables that aren't set."""

    names: tuple[str, ...]


def settings_from(env: Mapping[str, str], gateway: Path | None = None) -> Settings | Missing:
    """Read from environment variables. The endpoint's are named as OpenAI's own tools name them."""
    required = ("OPENAI_BASE_URL", "OPENAI_API_KEY")
    if missing := tuple(name for name in required if not env.get(name)):
        return Missing(missing)
    return Settings(
        base_url=env["OPENAI_BASE_URL"].rstrip("/"),
        api_key=env["OPENAI_API_KEY"],
        transcribe_model=env.get("WORKSPACE_TRANSCRIBE_MODEL", "gpt-4o-transcribe"),
        vocabulary=env.get("WORKSPACE_VOCABULARY", ""),
        fast_model=env.get("WORKSPACE_FAST_MODEL", FAST_MODEL),
        agent_model=env.get("WORKSPACE_AGENT_MODEL", AGENT_MODEL),
        agent_reasoning_effort=env.get("WORKSPACE_AGENT_REASONING_EFFORT", "low"),
        gateway=gateway,
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


# ---- Tools and results -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ToolCall:
    id: str
    name: str
    arguments: str
    """JSON, as the model wrote it (it may not be valid)."""


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
class Failure:
    message: str


# ---- Requests --------------------------------------------------------------------------


class _Transcription(TypedDict):
    text: str


class _ErrorDetail(TypedDict):
    message: str


# The SDK builds reply objects without validating them (a proxy's HTML page arrives as
# a `str`), so the calls read the raw body and validate only the fields used here.
_TRANSCRIPTION = TypeAdapter(_Transcription)
_ERROR_DETAIL = TypeAdapter(_ErrorDetail)


def route(settings: Settings) -> tuple[str, str]:
    """The base URL and key a client uses: the AI connection's, read afresh so a
    restarted gateway is reached on the next request, else the provider's own."""
    if settings.gateway is not None and (endpoint := read(settings.gateway)) is not None:
        return endpoint.base_url, endpoint.token
    return settings.base_url, settings.api_key


def async_client(settings: Settings, *, timeout_s: float, max_retries: int = 0) -> AsyncOpenAI:
    """The endpoint for every SDK model. The gateway's and the SDK's HTTP clients use
    the system's proxy settings and certificate store, so company TLS inspection works."""
    base_url, api_key = route(settings)
    return AsyncOpenAI(base_url=base_url, api_key=api_key, timeout=timeout_s, max_retries=max_retries)


def _client(settings: Settings, timeout_s: float) -> OpenAI:
    # A failed dictation is reported at once; the user or the meeting worker retries.
    base_url, api_key = route(settings)
    return OpenAI(base_url=base_url, api_key=api_key, timeout=timeout_s, max_retries=0)


def _failure(settings: Settings, error: APIStatusError | APIConnectionError) -> Failure:
    match error:
        case APIStatusError():
            try:
                detail = _ERROR_DETAIL.validate_python(error.body)["message"]
            except ValidationError:
                detail = error.response.reason_phrase
            return Failure(f"HTTP {error.status_code}: {detail}")
        case APIConnectionError():
            return Failure(f"can't reach {urlsplit(settings.base_url).netloc}: {error.__cause__ or error.message}")
        case _:
            assert_never(error)


def _unexpected(body: bytes) -> Failure:
    return Failure(f"unexpected reply: {body[:200].decode(errors='replace')}")


def transcribe(settings: Settings, audio: bytes, *, timeout_s: float = 60, context: str = "") -> str | Failure:
    """The text spoken in a WAV file."""
    prompt = "\n".join(part for part in (settings.vocabulary, context[-600:]) if part)
    try:
        with _client(settings, timeout_s) as client:
            reply = client.audio.transcriptions.with_raw_response.create(
                model=settings.transcribe_model,
                file=("speech.wav", audio, "audio/wav"),
                response_format="json",
                prompt=prompt or omit,
            ).content
    except (APIStatusError, APIConnectionError) as error:
        return _failure(settings, error)
    try:
        return _TRANSCRIPTION.validate_json(reply)["text"]
    except ValidationError:
        return _unexpected(reply)
