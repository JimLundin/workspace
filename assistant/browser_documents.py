"""Bounded document retrieval using the browser's authenticated network owner."""

import base64
import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event
from typing import Annotated

from pydantic import Field, TypeAdapter

from assistant.browser_values import BrowserError
from assistant.llm import Json
from automation.work_documents import LocalDocument


@dataclass(frozen=True, slots=True)
class Download:
    target_id: str
    url: str
    destination: LocalDocument


@dataclass(frozen=True, slots=True)
class Resource:
    success: bool = field(default=False, kw_only=True)
    status: Annotated[int, Field(alias="httpStatusCode")] = 0
    stream: str | None = None
    headers: frozendict[str, str] = frozendict()


@dataclass(frozen=True, slots=True)
class ResourceResponse:
    resource: Resource


@dataclass(frozen=True, slots=True)
class Chunk:
    data: str
    eof: bool = field(kw_only=True)
    encoded: Annotated[bool, Field(alias="base64Encoded")] = field(default=False, kw_only=True)


@dataclass(frozen=True, slots=True)
class Downloaded:
    path: str
    sha256: str
    size: Annotated[int, Field(ge=0)]
    content_type: str


type Transport = Callable[[str, dict[str, Json]], dict[str, Json]]
_RESOURCE = TypeAdapter(ResourceResponse)
_CHUNK = TypeAdapter(Chunk)
DOWNLOADED = TypeAdapter(Downloaded)
MAX_DOCUMENT = 32 * 1024 * 1024


def download(request: Download, cancel: Event, transport: Transport) -> Downloaded:
    resource = _RESOURCE.validate_python(
        transport("Network.loadNetworkResource", {"url": request.url, "options": {"disableCache": False, "includeCredentials": True}})
    ).resource
    if resource.stream is None:
        raise BrowserError("The browser did not return an attachment stream. Inspect its preview or download controls.")
    path = Path(request.destination.path)
    created = False
    try:
        if not resource.success or not 200 <= resource.status < 300:
            raise BrowserError("The authenticated attachment request failed. No file was collected.")
        headers = frozendict((key.casefold(), value) for key, value in resource.headers.items())
        content_type = headers.get("content-type", "").split(";", 1)[0].strip().casefold()
        if content_type in ("text/html", "application/xhtml+xml"):
            raise BrowserError("The browser returned an HTML page rather than a document. Inspect sign-in and the attachment preview.")
        # Exclusive creation preserves existing versions. This owner removes
        # only its incomplete file, and always closes its browser-owned stream.
        path.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        size = 0
        with path.open("xb") as output:
            created = True
            while True:
                if cancel.is_set():
                    raise BrowserError("Stopped while collecting the document.")
                chunk = _CHUNK.validate_python(transport("IO.read", {"handle": resource.stream, "size": 65536}))
                data = base64.b64decode(chunk.data, validate=True) if chunk.encoded else chunk.data.encode("utf-8")
                size += len(data)
                if size > MAX_DOCUMENT:
                    raise BrowserError("The attachment exceeds the 32 MiB collection limit. Keep its browser reference.")
                output.write(data)
                digest.update(data)
                if chunk.eof:
                    break
                if not data:
                    raise BrowserError("The document stream stopped making progress.")
        if size == 0:
            raise BrowserError("The attachment response was empty. No document was collected.")
        return Downloaded(str(path), digest.hexdigest(), size, content_type)
    except BaseException:
        if created:
            path.unlink(missing_ok=True)
        raise
    finally:
        # Stream cleanup must not depend on an already-cancelled tool event.
        transport("IO.close", {"handle": resource.stream})
