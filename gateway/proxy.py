"""The gateway's loopback HTTP server.

Each `/v1/...` request is checked against this boot's token and sent on to the
provider over one pooled connection. The reply is relayed chunk by chunk as it
arrives, so streamed (SSE) replies stay live. The gateway never retries: a POST
reaches the provider at most once, and clients keep their own retry policy. A
client that goes away closes the provider's stream with it.
"""

import contextlib
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Final, assert_never
from urllib.parse import urlsplit

from pydantic import TypeAdapter
lazy import httpx

from gateway.upstream import Unconfigured, Upstream, request_headers, response_headers, target

TIMEOUT_S: Final = 900.0
"""Longer than any client's own timeout (the agent's is 600 s), so the client decides."""

_ERROR = TypeAdapter(dict[str, dict[str, str]])


def provider_client() -> httpx.Client:
    """One pool for every request. Like the OpenAI SDK's own client, it follows the
    system's proxy settings and redirects."""
    return httpx.Client(timeout=httpx.Timeout(TIMEOUT_S, connect=15.0), follow_redirects=True)


def _bind(port: int, handler: type[BaseHTTPRequestHandler]) -> ThreadingHTTPServer:
    """Take back the previous port so clients built before a restart still reach us."""
    try:
        return ThreadingHTTPServer(("127.0.0.1", port), handler)
    except OSError:
        if port == 0:
            raise
        return ThreadingHTTPServer(("127.0.0.1", 0), handler)


class Gateway:
    """Owns the listening socket, its request threads and the provider pool."""

    __slots__ = ("_client", "_server", "_thread", "token", "upstream")

    def __init__(self, upstream: Upstream | Unconfigured, token: str, *, port: int = 0, client: Callable[[], httpx.Client] = provider_client) -> None:
        self.upstream = upstream
        self.token = token
        self._client = client()
        self._server = _bind(port, _handler(self))
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        return self._server.server_address[1]

    def start(self) -> None:
        """Serve on a background thread (tests); `serve` blocks instead."""
        self._thread = threading.Thread(target=self._server.serve_forever, name="gateway", daemon=True)
        self._thread.start()

    def serve(self) -> None:
        self._server.serve_forever()

    def close(self) -> None:
        if self._thread is not None:
            self._server.shutdown()
            self._thread.join()
        self._server.server_close()
        self._client.close()

    def relay(self, request: BaseHTTPRequestHandler) -> None:
        # Read the whole request before answering: replying over an unread upload
        # resets the connection, and the client sees no reason at all.
        if "Transfer-Encoding" in request.headers:
            request.close_connection = True
            _error(request, 411, "The AI connection needs a Content-Length.")
            return
        body = request.rfile.read(int(request.headers.get("Content-Length", "0")))
        if request.headers.get("Authorization") != f"Bearer {self.token}":
            _error(request, 401, "This is Workspace's AI connection; its token is in the keeper's state folder.")
            return
        match self.upstream:
            case Unconfigured(names=names):
                _error(request, 503, f"Set {', '.join(names)} for the AI connection, then restart Workspace.")
            case Upstream() as upstream:
                self._forward(request, upstream, body)
            case _:
                assert_never(self.upstream)

    def _forward(self, request: BaseHTTPRequestHandler, upstream: Upstream, body: bytes) -> None:
        url = target(upstream, request.path)
        if url is None:
            _error(request, 404, f"The AI connection forwards /v1/ paths, not {request.path}.")
            return
        outgoing = self._client.build_request(request.command, url, headers=request_headers(request.headers.items(), upstream), content=body)
        try:
            reply = self._client.send(outgoing, stream=True)
        except httpx.HTTPError as error:
            _error(request, 502, f"can't reach {urlsplit(upstream.base_url).netloc}: {error}")
            return
        with contextlib.closing(reply):
            request.send_response(reply.status_code)
            for name, value in response_headers(reply.headers.multi_items()):
                request.send_header(name, value)
            request.send_header("Transfer-Encoding", "chunked")
            request.end_headers()
            try:
                for chunk in reply.iter_raw():
                    if chunk:
                        request.wfile.write(b"%x\r\n%b\r\n" % (len(chunk), chunk))
                        request.wfile.flush()
                request.wfile.write(b"0\r\n\r\n")
            except OSError, httpx.HTTPError:
                # The client left, or the provider broke off: end both sides without a
                # terminating chunk, so the client sees the reply as incomplete.
                request.close_connection = True


def _error(request: BaseHTTPRequestHandler, status: int, message: str) -> None:
    """An OpenAI-shaped error, so clients report the message as the provider's would be."""
    body = _ERROR.dump_json({"error": {"message": message}})
    request.send_response(status)
    request.send_header("Content-Type", "application/json")
    request.send_header("Content-Length", str(len(body)))
    request.end_headers()
    request.wfile.write(body)


def _handler(gateway: Gateway) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        """Keep-alive: the SDK reuses its connection to us across requests."""

        def do_GET(self) -> None:
            gateway.relay(self)

        def do_POST(self) -> None:
            gateway.relay(self)

        def do_DELETE(self) -> None:
            gateway.relay(self)

        def log_message(self, format: str, *args: object) -> None:
            """Requests are not logged: their paths and timing are the clients' to record."""

    return Handler
