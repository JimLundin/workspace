"""The one loopback listener authenticates, bounds and decodes requests for every owner."""

from dataclasses import dataclass
from http.client import HTTPConnection
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import TypeAdapter

from assistant.local_bridge import ENDPOINT, MAX_REQUEST_BYTES, Contract, LocalBridge


@dataclass(frozen=True, slots=True)
class Echo:
    text: str


ECHO = Contract("/echo", TypeAdapter(Echo), TypeAdapter(Echo))


def answer(request: Echo) -> Echo:
    match request.text:
        case "unavailable":
            raise OSError("The owner's store is unavailable.")
        case "invalid":
            raise ValueError("The owner refused the request.")
        case text:
            return Echo(text.upper())


def send(endpoint: Path, body: bytes, headers: dict[str, str]) -> tuple[int, bytes]:
    location = urlsplit(ENDPOINT.validate_json(endpoint.read_bytes()).url)
    connection = HTTPConnection(location.netloc, timeout=2)
    try:
        connection.request("POST", location.path, body, headers)
        response = connection.getresponse()
        return response.status, response.read()
    finally:
        connection.close()


def test_bridge_serves_only_authenticated_bounded_typed_requests(tmp_path: Path) -> None:
    # Defects: accepting a missing or wrong bearer or another path, reading an
    # unbounded body, mistaking an invalid request or owner refusal for success,
    # or reporting a transient owner failure as the client's error.
    endpoint = tmp_path / "bridge.json"
    bridge = LocalBridge(endpoint, ECHO, answer)
    try:
        published = ENDPOINT.validate_json(endpoint.read_bytes())
        assert urlsplit(published.url).hostname == "127.0.0.1"
        bearer = {"Authorization": "Bearer " + published.token}
        request = b'{"text": "ready"}'
        assert send(endpoint, request, bearer) == (200, b'{"text":"READY"}')
        assert send(endpoint, request, {})[0] == 403
        assert send(endpoint, request, {"Authorization": "Bearer " + published.token[:-1]})[0] == 403
        assert send(endpoint, request, {"Authorization": "Bearer ünicode"})[0] == 403
        location = urlsplit(published.url)
        connection = HTTPConnection(location.netloc, timeout=2)
        connection.request("POST", "/other", request, bearer)
        assert connection.getresponse().status == 403
        connection.close()
        largest = request + b" " * (MAX_REQUEST_BYTES - len(request))
        assert send(endpoint, largest, bearer)[0] == 200
        # The size is refused from the header, before the body is read.
        assert send(endpoint, b"", {**bearer, "Content-Length": str(MAX_REQUEST_BYTES + 1)})[0] == 400
        assert send(endpoint, b"", bearer)[0] == 400
        assert send(endpoint, b'{"words": "ready"}', bearer)[0] == 400
        assert send(endpoint, b'{"text": "invalid"}', bearer)[0] == 400
        assert send(endpoint, b'{"text": "unavailable"}', bearer)[0] == 503
    finally:
        bridge.close()
    assert not endpoint.exists()


def test_closing_a_replaced_bridge_keeps_the_newer_endpoint(tmp_path: Path) -> None:
    # Defect: an older instance's close deletes the endpoint its replacement published.
    endpoint = tmp_path / "bridge.json"
    older = LocalBridge(endpoint, ECHO, answer)
    newer = LocalBridge(endpoint, ECHO, answer)
    try:
        older.close()
        assert ENDPOINT.validate_json(endpoint.read_bytes()).token == newer.token
    finally:
        newer.close()
    assert not endpoint.exists()
