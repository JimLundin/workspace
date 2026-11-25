from collections.abc import Iterable, Mapping
from dataclasses import dataclass

REQUIRED = ("OPENAI_BASE_URL", "OPENAI_API_KEY")

HOP_BY_HOP = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "trailers",
        "transfer-encoding",
        "upgrade",
    }
)
"""Headers that describe one connection, not the request; never forwarded."""
_REQUEST_DROPPED = HOP_BY_HOP | {"host", "authorization", "content-length"}
_RESPONSE_DROPPED = HOP_BY_HOP | {"content-length", "date", "server"}

type Headers = tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class Upstream:
    base_url: str
    """The provider's base, ending in `/v1`, as OpenAI's own libraries take it."""
    api_key: str


@dataclass(frozen=True, slots=True)
class Unconfigured:
    names: tuple[str, ...]


def upstream_from(env: Mapping[str, str]) -> Upstream | Unconfigured:
    if missing := tuple(name for name in REQUIRED if not env.get(name)):
        return Unconfigured(missing)
    return Upstream(env["OPENAI_BASE_URL"].rstrip("/"), env["OPENAI_API_KEY"])


def target(upstream: Upstream, path: str) -> str | None:
    if not path.startswith("/v1/"):
        return None
    return upstream.base_url + path.removeprefix("/v1")


def request_headers(
    headers: Iterable[tuple[str, str]], upstream: Upstream
) -> Headers:
    kept = tuple(
        (name, value)
        for name, value in headers
        if name.lower() not in _REQUEST_DROPPED
    )
    return (*kept, ("Authorization", f"Bearer {upstream.api_key}"))


def response_headers(headers: Iterable[tuple[str, str]]) -> Headers:
    return tuple(
        (name, value)
        for name, value in headers
        if name.lower() not in _RESPONSE_DROPPED
    )
