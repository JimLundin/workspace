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

from pydantic import TypeAdapter, ValidationError
lazy from openai import APIConnectionError, APIStatusError, OpenAI, omit

from link.endpoint import read
from winapi.pcm import RATE

MAX_SECONDS: Final = 300
"""Longest recording; the buffer for it (9.6 MB) is allocated once, at start."""
MIN_SECONDS: Final = 0.3
"""Shorter recordings are accidental taps, and aren't sent."""

# ---- Settings --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Settings:
    base_url: str
    """The endpoint's base, as OpenAI's own libraries take it: `https://.../v1`."""
    api_key: str
    transcribe_model: str
    vocabulary: str
    """Names and terms to expect when transcribing; helps with jargon. Empty: none."""
    gateway: Path | None = None
    """Where the AI connection publishes its endpoint; requests go through it once it
    has. None calls `base_url` directly."""


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


# ---- Results ---------------------------------------------------------------------------


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
