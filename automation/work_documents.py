"""Document locations at the personal-work boundary; content stays with its source."""

import hashlib
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Annotated, Literal
from urllib.parse import unquote, urlsplit

from pydantic import Field


def checked_url(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.username or parsed.password:
        raise ValueError("Document links cannot contain credentials.")
    if parsed.scheme == "https" and parsed.hostname:
        return url
    if parsed.scheme == "file":
        path = "//" + parsed.netloc + unquote(parsed.path) if parsed.netloc else unquote(parsed.path).lstrip("/")
        if PureWindowsPath(path).is_absolute():
            return url
    raise ValueError("Choose an absolute local document or an HTTPS document link.")


@dataclass(frozen=True, slots=True)
class LocalDocument:
    path: Annotated[str, Field(min_length=1, max_length=4000)]
    kind: Literal["local"] = "local"

    def __post_init__(self) -> None:
        if not PureWindowsPath(self.path).is_absolute():
            raise ValueError("Local documents need an absolute Windows path.")

    @property
    def url(self) -> str:
        return Path(self.path).as_uri()


@dataclass(frozen=True, slots=True)
class WebDocument:
    url: Annotated[str, Field(min_length=1, max_length=4000)]
    kind: Literal["web"] = "web"

    def __post_init__(self) -> None:
        if urlsplit(checked_url(self.url)).scheme != "https":
            raise ValueError("Web documents need an HTTPS link.")


type DocumentReference = Annotated[LocalDocument | WebDocument, Field(discriminator="kind")]


def document_identity(url: str) -> str:
    canonical = checked_url(url)
    if urlsplit(canonical).scheme == "file":
        canonical = unquote(canonical).casefold()
    return hashlib.sha256(canonical.encode()).hexdigest()
