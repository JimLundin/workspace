"""One authenticated loopback listener for each local client contract.

The bridge owns the listening socket, bearer authentication, the bounded request
body, typed request/response decoding and the endpoint file its client reads.
Owners supply one typed handler and never see HTTP.
"""

import contextlib
import hmac
import secrets
import threading
from collections.abc import Callable
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from pydantic import TypeAdapter

MAX_REQUEST_BYTES = 64_000
# shutdown() waits for the serving loop's next poll. A short poll keeps
# application close and isolated tests quick at a negligible idle cost.
_POLL_SECONDS = 0.1
_ADDRESS = TypeAdapter(tuple[str, int])


@dataclass(frozen=True, slots=True)
class Endpoint:
    """The published address and bearer token a local client reads."""

    url: str
    token: str


ENDPOINT = TypeAdapter(Endpoint)


@dataclass(frozen=True, slots=True)
class Contract[C, R]:
    """The wire contract shared by a bridge and its client."""

    path: str
    commands: TypeAdapter[C]
    responses: TypeAdapter[R]


class LocalBridge[C, R]:
    """Serves one contract on 127.0.0.1 until closed.

    Invalid requests and handler `ValueError`/`TypeError` refusals answer 400;
    handler `OSError` answers 503. Typed refusals belong to the response contract.
    """

    __slots__ = ("endpoint", "server", "thread", "token")

    def __init__(self, endpoint: Path, contract: Contract[C, R], handle: Callable[[C], R]) -> None:
        self.endpoint = endpoint
        self.token = secrets.token_urlsafe(32)
        authorization = ("Bearer " + self.token).encode()

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: object) -> None:
                pass  # Requests may carry private messages or command arguments.

            def do_POST(self) -> None:
                offered = self.headers.get("Authorization", "").encode("utf-8", "replace")
                if self.path != contract.path or not hmac.compare_digest(offered, authorization):
                    self.send_error(403)
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= MAX_REQUEST_BYTES:
                        raise ValueError("Invalid local request size.")
                    output = contract.responses.dump_json(handle(contract.commands.validate_json(self.rfile.read(length))))
                except ValueError, TypeError:
                    self.send_error(400)
                    return
                except OSError:
                    self.send_error(503)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(output)))
                self.end_headers()
                with contextlib.suppress(BrokenPipeError, ConnectionResetError):
                    self.wfile.write(output)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        port = _ADDRESS.validate_python(self.server.socket.getsockname())[1]
        endpoint.parent.mkdir(parents=True, exist_ok=True)
        temporary = endpoint.with_suffix(".tmp")
        temporary.write_bytes(ENDPOINT.dump_json(Endpoint(f"http://127.0.0.1:{port}{contract.path}", self.token)))
        temporary.chmod(0o600)
        temporary.replace(endpoint)
        self.thread = threading.Thread(target=self.serve, name="Local bridge " + contract.path, daemon=True)
        self.thread.start()

    def serve(self) -> None:
        self.server.serve_forever(_POLL_SECONDS)

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        # A newer instance may already own the endpoint file.
        with contextlib.suppress(OSError, ValueError):
            if ENDPOINT.validate_json(self.endpoint.read_bytes()).token == self.token:
                self.endpoint.unlink()
