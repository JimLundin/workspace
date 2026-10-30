"""Bounded, cancellable HTTPS for Microsoft authentication and Graph."""

import asyncio
import contextlib
import ssl
import threading
from dataclasses import dataclass
from math import isfinite

from pydantic import TypeAdapter
lazy import httpx

from assistant.llm import Json

_JSON_VALUE = TypeAdapter(Json)


class GraphError(OSError):
    pass


@dataclass(frozen=True, slots=True)
class Request:
    """One HTTP exchange; credentials and payload remain private to transport."""

    method: str
    url: str
    headers: tuple[tuple[str, str], ...] = ()
    body: bytes | None = None


class Http:
    __slots__ = ("socket_timeout", "timeout")

    def __init__(self, *, timeout: float = 25, socket_timeout: float = 20) -> None:
        if not all(isfinite(value) and value > 0 for value in (timeout, socket_timeout)):
            raise ValueError("HTTP timeouts must be finite and positive.")
        self.timeout, self.socket_timeout = timeout, socket_timeout

    def request(
        self,
        request: Request,
        cancel: threading.Event,
    ) -> tuple[int, dict[str, Json]]:
        if cancel.is_set():
            raise GraphError("Stopped before contacting Microsoft.")
        return asyncio.run(self._request(request, cancel))

    async def _request(
        self,
        request: Request,
        cancel: threading.Event,
    ) -> tuple[int, dict[str, Json]]:
        async def receive() -> tuple[int, dict[str, Json]]:
            async with httpx.AsyncClient(verify=ssl.create_default_context(), timeout=self.socket_timeout, follow_redirects=False) as client:
                return await self._receive(client, request)

        pending = asyncio.create_task(receive())
        try:
            async with asyncio.timeout(self.timeout):
                while not pending.done():
                    if cancel.is_set():
                        raise GraphError("Stopped. A request already sent to Microsoft may have completed; check its result before retrying.")
                    await asyncio.sleep(0.05)
                return await pending
        except (httpx.HTTPError, ValueError, TimeoutError) as error:
            # Never include request headers, response bodies or token endpoint
            # diagnostics in an exception that the agent could journal.
            raise GraphError("Microsoft's request failed or timed out. Check the result before retrying a send.") from error
        finally:
            if not pending.done():
                pending.cancel()
            with contextlib.suppress(asyncio.CancelledError, GraphError, httpx.HTTPError, ValueError):
                await pending

    async def _receive(
        self,
        client: httpx.AsyncClient,
        request: Request,
    ) -> tuple[int, dict[str, Json]]:
        """Read one bounded response without redirects or automatic retries."""
        async with client.stream(request.method, request.url, headers=dict(request.headers), content=request.body) as response:
            data = bytearray()
            async for chunk in response.aiter_bytes():
                data.extend(chunk)
                if len(data) > 1_000_000:
                    raise GraphError("Microsoft's response exceeded the size limit.")
            match _JSON_VALUE.validate_json(data or b"{}"):
                case dict() as result:
                    return response.status_code, result
                case _:
                    raise GraphError("Microsoft returned an unexpected response.")
