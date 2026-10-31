"""Keep an approved browser connection alive independently of Workspace reloads."""

import contextlib
import hmac
import os
import secrets
import select
import socket
import struct
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Generator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Literal
lazy import fcntl
lazy import msvcrt

from pydantic import Field, TypeAdapter, ValidationError

from assistant.browser_session import MAX_RESPONSE, BrowserSession, NativeSessions, Product, SessionOpener
from assistant.browser_values import (
    BrowserError,
    DisconnectedError,
    InterruptedError,
    NavigationContextError,
    TargetSession,
    decoded,
    navigation_context_error,
)
from automation.json_value import Json
lazy from runtime import activate
lazy from winapi.protection import protect, unprotect

MAX_CLIENTS = 8


@dataclass(frozen=True, slots=True)
class Endpoint:
    port: Annotated[int, Field(strict=True, ge=1, le=65535)]
    token: Annotated[str, Field(strict=True, min_length=64, max_length=64)]
    pid: Annotated[int, Field(strict=True, gt=0)]

    def exchange(self, request: HostRequest, cancel: threading.Event, *, timeout: float) -> frozendict[str, Json]:
        """One request over its own local socket; the host's refusal becomes the matching error."""
        if cancel.is_set():
            raise InterruptedError("Stopped before contacting the browser host.")
        try:
            with socket.create_connection(("127.0.0.1", self.port), timeout=0.5) as stream:
                stream.settimeout(0.1)
                stream.sendall(frame(_REQUEST.dump_json(request)))
                raw = receive(stream, cancel, time.monotonic() + timeout)
        except BrowserError:
            raise
        except OSError as error:
            raise DisconnectedError("Workspace's browser connection host is unavailable. Reconnect explicitly to continue.") from error
        try:
            reply = _REPLY.validate_json(raw)
        except ValidationError as error:
            raise BrowserError("The browser host returned an invalid reply.") from error
        match reply:
            case Answer(result):
                return result
            case Refusal(Failure("DisconnectedError", message)):
                raise DisconnectedError(message)
            case Refusal(Failure("InterruptedError", message)):
                raise InterruptedError(message)
            case Refusal(Failure(kind, message)) if kind == "NavigationContextError" or navigation_context_error(message):
                raise NavigationContextError(message)
            case Refusal(Failure(_kind, message)):
                raise BrowserError(message)


# The local exchange keeps one flat JSON object per request: a host started by
# an earlier Workspace version stays reachable after a source update.
type ClientId = Annotated[str, Field(strict=True, pattern=r"^[0-9a-f]{32}$")]


@dataclass(frozen=True, slots=True)
class Credential:
    token: Annotated[str, Field(strict=True)]


@dataclass(frozen=True, slots=True)
class StatusRequest:
    token: str
    operation: Literal["status"] = "status"


@dataclass(frozen=True, slots=True)
class ConnectRequest:
    token: str
    client: ClientId
    operation: Literal["connect"] = "connect"


@dataclass(frozen=True, slots=True)
class ReleaseRequest:
    token: str
    client: ClientId
    operation: Literal["release"] = "release"


@dataclass(frozen=True, slots=True)
class CallRequest:
    """One CDP command on behalf of a client, within its own page sessions."""

    token: str
    client: ClientId
    method: Annotated[str, Field(strict=True, min_length=1, max_length=256)]
    params: frozendict[str, Json]
    session: Annotated[str, Field(strict=True, max_length=512)] = ""
    timeout: Annotated[float, Field(strict=True, gt=0, le=60, allow_inf_nan=False)] = 15
    operation: Literal["call"] = "call"


type HostRequest = Annotated[StatusRequest | ConnectRequest | ReleaseRequest | CallRequest, Field(discriminator="operation")]


@dataclass(frozen=True, slots=True)
class HostStatus:
    connected: bool = field(kw_only=True)
    generation: int
    clients: int
    pid: int


@dataclass(frozen=True, slots=True)
class Failure:
    kind: str
    message: str


@dataclass(frozen=True, slots=True)
class Answer:
    result: frozendict[str, Json]


@dataclass(frozen=True, slots=True)
class Refusal:
    error: Failure


type Reply = Answer | Refusal

_ENDPOINT = TypeAdapter(Endpoint)
_CREDENTIAL = TypeAdapter(Credential)
_REQUEST = TypeAdapter[StatusRequest | ConnectRequest | ReleaseRequest | CallRequest](HostRequest)
_REPLY = TypeAdapter[Reply](Reply)
_STATUS = TypeAdapter(HostStatus)
_RESULT = TypeAdapter(frozendict[str, Json])
_SESSION = TypeAdapter(TargetSession)


def sealed(data: bytes, *, opening: bool = False) -> bytes:
    if sys.platform != "win32":
        return data

    return unprotect(data) if opening else protect(data)


def endpoint(folder: Path) -> Endpoint:
    try:
        return _ENDPOINT.validate_json(sealed((folder / "endpoint.bin").read_bytes(), opening=True))
    except ValidationError as error:
        raise BrowserError("The browser connection host published an invalid endpoint.") from error


def frame(data: bytes) -> bytes:
    if len(data) > MAX_RESPONSE:
        raise BrowserError("The browser host exchange exceeded its size limit.")
    return struct.pack("!I", len(data)) + data


def receive(stream: socket.socket, cancel: threading.Event, deadline: float) -> bytes:
    def read(size: int) -> bytes:
        data = bytearray()
        while len(data) < size:
            if cancel.is_set():
                raise InterruptedError("Stopped while waiting for the browser host. Inspect any action already started.")
            if time.monotonic() >= deadline:
                raise BrowserError("The browser host did not answer in time. Inspect any action already started before retrying.")
            try:
                chunk = stream.recv(min(size - len(data), 65536))
            except TimeoutError:
                continue
            if not chunk:
                raise DisconnectedError("The browser connection host disconnected. Reconnect explicitly to continue.")
            data.extend(chunk)
        return bytes(data)

    size = int.from_bytes(read(4), byteorder="big")
    if not 0 < size <= MAX_RESPONSE:
        raise BrowserError("The browser host exchange exceeded its size limit.")
    return read(size)


class HostedConnection:
    __slots__ = ("closed", "identity", "location")

    def __init__(self, location: Endpoint) -> None:
        self.location, self.identity, self.closed = location, uuid.uuid4().hex, False

    def call(
        self,
        method: str,
        params: dict[str, Json],
        cancel: threading.Event,
        *,
        session: str = "",
        timeout: float = 15,
    ) -> dict[str, Json]:
        if self.closed:
            raise DisconnectedError("This browser client is disconnected.")
        request = CallRequest(self.location.token, self.identity, method, frozendict(params), session, timeout)
        return dict(self.location.exchange(request, cancel, timeout=timeout + 0.5))

    def close(self) -> None:
        if not self.closed:
            self.closed = True
            with contextlib.suppress(OSError, ValueError):
                self.location.exchange(ReleaseRequest(self.location.token, self.identity), threading.Event(), timeout=4)


@contextlib.contextmanager
def lease(folder: Path) -> Generator[None]:
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / "host.lock").open("a+b") as stream:
        if not stream.tell():
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        if sys.platform == "win32":
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


class Host:
    __slots__ = ("clients", "generation", "lock", "opener", "product", "session")

    def __init__(self, product: Product, opener: SessionOpener) -> None:
        self.product, self.opener = product, opener
        self.session: BrowserSession | None = None
        self.lock = threading.Lock()
        self.clients: dict[str, set[str]] = {}
        self.generation = 0

    def handle(self, request: HostRequest, cancel: threading.Event) -> frozendict[str, Json]:
        match request:
            case StatusRequest():
                status = HostStatus(self.generation, len(self.clients), os.getpid(), connected=self.session is not None)
                return _RESULT.validate_json(_STATUS.dump_json(status))
            case ConnectRequest() | ReleaseRequest() | CallRequest():
                pass
        while not self.lock.acquire(timeout=0.1):
            if cancel.is_set():
                raise InterruptedError("Stopped before the queued browser request started.")
        try:
            if cancel.is_set():
                raise InterruptedError("Stopped before the browser request started.")
            return self._handle(request, cancel)
        finally:
            self.lock.release()

    def _handle(self, request: ConnectRequest | ReleaseRequest | CallRequest, cancel: threading.Event) -> frozendict[str, Json]:
        match request:
            case ConnectRequest(client=client):
                if self.session is None:
                    self.session = self.opener.open(self.product, cancel)
                    self.generation += 1
                self.clients.setdefault(client, set())
                return frozendict()
            case ReleaseRequest(client=client):
                sessions = self.clients.pop(client, set())
                if self.session is not None:
                    for session in sessions:
                        with contextlib.suppress(OSError):
                            self.session.connection.call("Target.detachFromTarget", {"sessionId": session}, cancel, timeout=1)
                return frozendict()
            case CallRequest(client=client) if client not in self.clients or self.session is None:
                raise DisconnectedError("The approved browser connection is unavailable. Use Connect Teams to reconnect explicitly.")
            case CallRequest(method="Browser.close"):
                raise BrowserError("Workspace does not own the personal browser's lifetime.")
            case CallRequest(client=client, session=session) if session and session not in self.clients[client]:
                raise BrowserError("That browser page session belongs to another client.")
            case CallRequest(client=client):
                return self._call(client, request, cancel)

    def _call(self, client: str, request: CallRequest, cancel: threading.Event) -> frozendict[str, Json]:
        if self.session is None:
            raise DisconnectedError("The approved browser connection is unavailable. Use Connect Teams to reconnect explicitly.")
        try:
            result = self.session.connection.call(request.method, dict(request.params), cancel, session=request.session, timeout=request.timeout)
        except DisconnectedError:
            self.session.close()
            self.session = None
            self.clients.clear()
            raise
        match request.method:
            case "Target.attachToTarget":
                self.clients[client].add(decoded(_SESSION, result, "The browser did not attach that page.").session_id)
            case "Target.detachFromTarget":
                self.clients[client].discard(decoded(_SESSION, dict(request.params), "The detached page session is invalid.").session_id)
            case _:
                pass
        return frozendict(result)

    def close(self) -> None:
        with self.lock:
            if self.session is not None:
                self.session.close()
                self.session = None


class Server:
    __slots__ = ("folder", "host", "limit", "location", "stop", "stream", "thread")

    def __init__(self, folder: Path, host: Host) -> None:
        self.folder, self.host = folder, host
        self.stream = socket.socket()
        self.stream.bind(("127.0.0.1", 0))
        self.stream.listen(MAX_CLIENTS)
        self.stream.settimeout(0.25)
        match self.stream.getsockname():
            case (str(), int() as port):
                self.location = Endpoint(port, secrets.token_hex(32), os.getpid())
            case _:
                raise BrowserError("The browser host could not bind its local port.")
        self.stop = threading.Event()
        self.limit = threading.BoundedSemaphore(MAX_CLIENTS)
        self.thread = threading.Thread(target=self.run, name="browser host listener", daemon=True)

    def start(self) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        candidate = self.folder / "endpoint.pending"
        descriptor = os.open(candidate, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(sealed(_ENDPOINT.dump_json(self.location)))
        candidate.replace(self.folder / "endpoint.bin")
        self.thread.start()

    def run(self) -> None:
        while not self.stop.is_set():
            try:
                stream, _address = self.stream.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            if not self.limit.acquire(blocking=False):
                stream.close()
                continue
            threading.Thread(target=self.client, args=(stream,), name="browser host exchange", daemon=True).start()

    def client(self, stream: socket.socket) -> None:
        cancel, finished = threading.Event(), threading.Event()

        def watch() -> None:
            while not finished.wait(0.1):
                if self.stop.is_set():
                    cancel.set()
                    return
                try:
                    watched: list[socket.socket] = [stream]
                    empty: list[socket.socket] = []
                    selection: tuple[list[socket.socket], list[socket.socket], list[socket.socket]] = select.select(watched, empty, empty, 0.1)
                    ready = selection[0]
                    if ready:
                        cancel.set()  # Each local socket carries one request; EOF cancels it.
                        return
                except OSError, ValueError:
                    cancel.set()
                    return

        watcher: threading.Thread | None = None
        try:
            stream.settimeout(0.1)
            raw = receive(stream, cancel, time.monotonic() + 3)
            # Only an authenticated client learns whether its request was valid.
            if not hmac.compare_digest(_CREDENTIAL.validate_json(raw).token, self.location.token):
                return
            watcher = threading.Thread(target=watch, name="browser host cancellation", daemon=True)
            watcher.start()
            reply: Reply
            try:
                reply = Answer(self.host.handle(_REQUEST.validate_json(raw), cancel))
            except ValidationError:
                reply = Refusal(Failure("BrowserError", "The browser host request is invalid."))
            except (OSError, ValueError) as error:
                reply = Refusal(Failure(type(error).__name__, str(error)[:1000]))
            if not cancel.is_set():
                stream.sendall(frame(_REPLY.dump_json(reply)))
        except OSError, ValueError:
            pass
        finally:
            finished.set()
            if watcher is not None:
                watcher.join(timeout=0.3)
            stream.close()
            self.limit.release()

    def close(self) -> None:
        self.stop.set()
        self.stream.close()
        self.thread.join(timeout=1)
        self.host.close()
        with contextlib.suppress(OSError, ValueError):
            if endpoint(self.folder) == self.location:
                (self.folder / "endpoint.bin").unlink()


def connect_shared(folder: Path, product: Product, cancel: threading.Event) -> HostedConnection:
    location: Endpoint | None = None
    try:
        location = endpoint(folder)
        location.exchange(StatusRequest(location.token), cancel, timeout=1)
    except InterruptedError:
        raise
    except OSError, ValueError:
        location = None
    if location is None:
        flags = 0x0000_0208 if sys.platform == "win32" else 0
        subprocess.Popen(
            [sys.executable, "-B", "-m", "assistant.browser_host", product.value, str(folder)],
            cwd=Path(__file__).parents[1],
            creationflags=flags,
            start_new_session=sys.platform != "win32",
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + 8
        while location is None and time.monotonic() < deadline:
            if cancel.wait(0.1):
                raise InterruptedError("Stopped before the browser connection host was ready.")
            try:
                found = endpoint(folder)
                found.exchange(StatusRequest(found.token), cancel, timeout=1)
                location = found
            except InterruptedError:
                raise
            except OSError, ValueError:
                pass
    if location is None:
        raise BrowserError("Workspace's browser connection host could not start.")
    connection = HostedConnection(location)
    location.exchange(ConnectRequest(location.token, connection.identity), cancel, timeout=65)
    return connection


def main() -> None:

    activate()
    product, folder = Product(sys.argv[1]), Path(sys.argv[2])
    try:
        with lease(folder):
            server = Server(folder, Host(product, NativeSessions(folder / "unused")))
            server.start()
            try:
                while not server.stop.wait(30):
                    # Browser exit ends the host; an ordinary command timeout does not reconnect it.
                    if server.host.lock.acquire(blocking=False):
                        try:
                            if server.host.session is not None:
                                server.host.session.connection.call("Browser.getVersion", {}, threading.Event(), timeout=5)
                        except DisconnectedError:
                            break
                        except OSError:
                            pass
                        finally:
                            server.host.lock.release()
            finally:
                server.close()
    except OSError:
        return  # Another client may have started the one leased host first.


if __name__ == "__main__":
    main()
