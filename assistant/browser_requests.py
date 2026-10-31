"""Typed requests to the automation browser, one variant per operation.

The browser tool family validates the model's arguments into these once, at
its seam; in-process callers construct them directly. Field names and bounds
of the directly validated variants are the model's tool contract.
"""

from dataclasses import dataclass, field
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import Field

from assistant.browser_session import Product, Source
from assistant.browser_values import (
    BrowserError,
    Closure,
    DefaultGroup,
    Destination,
    Flag,
    Offset,
    PageList,
    StripQuery,
    TabEdit,
)

type PageId = Annotated[str, Field(strict=True, min_length=1, max_length=128)]
type FrameId = Annotated[str, Field(strict=True, max_length=128)]


def web_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
    except ValueError as error:
        raise BrowserError("Use a valid HTTP(S) page URL.") from error
    if value == "about:blank":
        return value
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password or any(ord(c) < 32 for c in value):
        raise BrowserError("Use an http(s) page URL without embedded credentials, or about:blank.")
    return value


@dataclass(frozen=True, slots=True)
class Attach:
    """Connect the user's running browser; without a product, keep the current one (Edge by default)."""

    browser: Product | None = None


@dataclass(frozen=True, slots=True)
class Open:
    """Navigate an exact page, or a new background tab placed in a group and window."""

    url: str
    target_id: str = ""
    source: Source | None = None
    placement: Destination = DefaultGroup.WORKSPACE
    window_id: int | None = None


@dataclass(frozen=True, slots=True)
class SignIn:
    """Open Workspace's separate profile visibly so the user can sign in."""

    url: Annotated[str, Field(strict=True, max_length=4000)]


@dataclass(frozen=True, slots=True)
class PageSnapshot:
    target_id: PageId
    frame_id: FrameId = ""
    offset: Offset = 0
    limit: Annotated[int, Field(strict=True, ge=1, le=100)] = 60
    text_offset: Annotated[int, Field(strict=True, ge=0, le=10_000_000)] = 0
    frame_offset: Offset = 0


@dataclass(frozen=True, slots=True)
class PageAction:
    """Act on a control from the latest snapshot; `id` is that snapshot's control id."""

    target_id: PageId
    id: Annotated[str, Field(strict=True, min_length=1, max_length=64)]
    action: Literal["click", "fill", "select", "check"]
    value: Annotated[str, Field(strict=True, max_length=60_000)] = ""
    frame_id: FrameId = ""
    checked: Flag = field(default=True, kw_only=True)


@dataclass(frozen=True, slots=True)
class Evaluate:
    target_id: PageId
    expression: Annotated[str, Field(strict=True, min_length=1, max_length=60_000, pattern=r"\S")]
    frame_id: FrameId = ""
    timeout_seconds: Annotated[int, Field(strict=True, ge=1, le=30)] = 15


@dataclass(frozen=True, slots=True)
class Screenshot:
    target_id: PageId


@dataclass(frozen=True, slots=True)
class Activate:
    """Bring an exact page forward, without session-local native tab metadata."""

    target_id: str


type Status = PageList | StripQuery
type BrowserRequest = Attach | Open | SignIn | Status | TabEdit | Closure | PageSnapshot | PageAction | Evaluate | Screenshot | Activate
