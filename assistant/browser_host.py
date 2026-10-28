"""Keep an approved browser connection alive independently of Workspace reloads."""

import contextlib
import hmac
import json
import math
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
from dataclasses import dataclass
from pathlib import Path
from typing import cast
lazy import fcntl
lazy import msvcrt

from assistant.browser_session import MAX_RESPONSE, BrowserSession, NativeSessions, Product, SessionOpener
from assistant.browser_values import (
    BrowserError,
    DisconnectedError,
    InterruptedError,
    NavigationContextError,
    mapping,
    navigation_context_error,
    text,
)
from assistant.llm import Json
lazy from runtime import activate
lazy from winapi.protection import protect, unprotect

MAX_CLIENTS = 8


@dataclass(frozen=True, slots=True)
class Endpoint:
    port: int
    token: str
    pid: int


def sealed(data: bytes, *, opening: bool = False) -> bytes:
    if sys.platform != "win32":
        return data

    return unprotect(data) if opening else protect(data)


def endpoint(folder: Path) -> Endpoint:
    value = mapping(cast(Json, json.loads(sealed((folder / "endpoint.bin").read_bytes(), opening=True))))
    port, pid, token = value.get("port"), value.get("pid"), value.get("token")
    if (type(port) is not int or not 1 <= port <= 65535 or type(pid) is not int or pid <= 0
            or not isinstance(token, str) or len(token) != 64):
        raise BrowserError("The browser connection host published an invalid endpoint.")
    return Endpoint(port, token, pid)


def frame(value: dict[str, Json]) -> bytes:
    data = json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
    if len(data) > MAX_RESPONSE:
        raise BrowserError("The browser host exchange exceeded its size limit.")
    return struct.pack("!I", len(data)) + data


def receive(stream: socket.socket, cancel: threading.Event, deadline: float) -> dict[str, Json]:
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
    return mapping(cast(Json, json.loads(read(size))))


def exchange(location: Endpoint, request: dict[str, Json], cancel: threading.Event, *, timeout: float) -> dict[str, Json]:
    if cancel.is_set():
        raise InterruptedError("Stopped before contacting the browser host.")
    try:
        with socket.create_connection(("127.0.0.1", location.port), timeout=.5) as stream:
            stream.settimeout(.1)
            stream.sendall(frame({**request, "token": location.token}))
            reply = receive(stream, cancel, time.monotonic() + timeout)
    except BrowserError:
        raise
    except OSError as error:
        raise DisconnectedError("Workspace's browser connection host is unavailable. Reconnect explicitly to continue.") from error
    if "error" in reply:
        failure = mapping(reply["error"])
        message = text(failure, "message", "The browser host could not complete this request.")
        match failure.get("kind"):
            case "DisconnectedError":
                raise DisconnectedError(message)
            case "InterruptedError":
                raise InterruptedError(message)
            case _:
                if failure.get("kind") == "NavigationContextError" or navigation_context_error(message):
                    raise NavigationContextError(message)
                raise BrowserError(message)
    return mapping(reply.get("result", {}))


class HostedConnection:
    __slots__ = ("closed", "identity", "location")

    def __init__(self, location: Endpoint) -> None:
        self.location, self.identity, self.closed = location, uuid.uuid4().hex, False

    def call(
        self, method: str, params: dict[str, Json], cancel: threading.Event, *, session: str = "", timeout: float = 15,
    ) -> dict[str, Json]:
        if self.closed:
            raise DisconnectedError("This browser client is disconnected.")
        return exchange(self.location, {"operation": "call", "client": self.identity, "method": method, "params": params,
                                        "session": session, "timeout": timeout}, cancel, timeout=timeout + .5)

    def close(self) -> None:
        if not self.closed:
            self.closed = True
            with contextlib.suppress(OSError, ValueError):
                exchange(self.location, {"operation": "release", "client": self.identity}, threading.Event(), timeout=4)


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

    def handle(self, request: dict[str, Json], cancel: threading.Event) -> dict[str, Json]:
        if request.get("operation") == "status":
            return {"connected": self.session is not None, "generation": self.generation, "clients": len(self.clients), "pid": os.getpid()}
        while not self.lock.acquire(timeout=.1):
            if cancel.is_set():
                raise InterruptedError("Stopped before the queued browser request started.")
        try:
            if cancel.is_set():
                raise InterruptedError("Stopped before the browser request started.")
            operation = request.get("operation")
            client = text(request, "client")
            if len(client) != 32 or any(char not in "0123456789abcdef" for char in client):
                raise BrowserError("The browser host request has an invalid client identity.")
            if operation == "connect":
                if self.session is None:
                    self.session = self.opener.open(self.product, cancel)
                    self.generation += 1
                self.clients.setdefault(client, set())
                return {"generation": self.generation, "pid": os.getpid()}
            if operation == "release":
                sessions = self.clients.pop(client, set())
                if self.session is not None:
                    for session in sessions:
                        with contextlib.suppress(OSError):
                            self.session.connection.call("Target.detachFromTarget", {"sessionId": session}, cancel, timeout=1)
                return {}
            if operation != "call" or client not in self.clients or self.session is None:
                raise DisconnectedError("The approved browser connection is unavailable. Use Connect Teams to reconnect explicitly.")
            method, session = text(request, "method"), text(request, "session")
            timeout = request.get("timeout")
            if (not method or len(method) > 256 or len(session) > 512 or isinstance(timeout, bool)
                    or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 0 < timeout <= 60):
                raise BrowserError("The browser host command is invalid.")
            if method == "Browser.close":
                raise BrowserError("Workspace does not own the personal browser's lifetime.")
            if session and session not in self.clients[client]:
                raise BrowserError("That browser page session belongs to another client.")
            try:
                result = self.session.connection.call(method, mapping(request.get("params", {})), cancel, session=session, timeout=timeout)
            except DisconnectedError:
                self.session.close()
                self.session = None
                self.clients.clear()
                raise
            if method == "Target.attachToTarget":
                self.clients[client].add(text(result, "sessionId"))
            elif method == "Target.detachFromTarget":
                self.clients[client].discard(text(mapping(request.get("params", {})), "sessionId"))
            return result
        finally:
            self.lock.release()

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
        self.stream.settimeout(.25)
        _address, port = cast(tuple[str, int], self.stream.getsockname())
        self.location = Endpoint(port, secrets.token_hex(32), os.getpid())
        self.stop = threading.Event()
        self.limit = threading.BoundedSemaphore(MAX_CLIENTS)
        self.thread = threading.Thread(target=self.run, name="browser host listener", daemon=True)

    def start(self) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        candidate = self.folder / "endpoint.pending"
        descriptor = os.open(candidate, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(sealed(json.dumps(dict[str, Json](port=self.location.port, token=self.location.token, pid=self.location.pid)).encode()))
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
            while not finished.wait(.1):
                if self.stop.is_set():
                    cancel.set()
                    return
                try:
                    watched: list[socket.socket] = [stream]
                    empty: list[socket.socket] = []
                    selection: tuple[list[socket.socket], list[socket.socket], list[socket.socket]] = select.select(watched, empty, empty, .1)
                    ready = selection[0]
                    if ready:
                        cancel.set()  # Each local socket carries one request; EOF cancels it.
                        return
                except (OSError, ValueError):
                    cancel.set()
                    return

        watcher: threading.Thread | None = None
        try:
            stream.settimeout(.1)
            request = receive(stream, cancel, time.monotonic() + 3)
            if not hmac.compare_digest(text(request, "token"), self.location.token):
                return
            watcher = threading.Thread(target=watch, name="browser host cancellation", daemon=True)
            watcher.start()
            try:
                reply: dict[str, Json] = {"result": self.host.handle(request, cancel)}
            except (OSError, ValueError) as error:
                reply = {"error": {"kind": type(error).__name__, "message": str(error)[:1000]}}
            if not cancel.is_set():
                stream.sendall(frame(reply))
        except (OSError, ValueError):
            pass
        finally:
            finished.set()
            if watcher is not None:
                watcher.join(timeout=.3)
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
        exchange(location, {"operation": "status"}, cancel, timeout=1)
    except InterruptedError:
        raise
    except (OSError, ValueError):
        location = None
    if location is None:
        flags = 0x0000_0208 if sys.platform == "win32" else 0
        subprocess.Popen([sys.executable, "-B", "-m", "assistant.browser_host", product.value, str(folder)],
                         cwd=Path(__file__).parents[1], creationflags=flags, start_new_session=sys.platform != "win32",
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + 8
        while location is None and time.monotonic() < deadline:
            if cancel.wait(.1):
                raise InterruptedError("Stopped before the browser connection host was ready.")
            try:
                found = endpoint(folder)
                exchange(found, {"operation": "status"}, cancel, timeout=1)
                location = found
            except InterruptedError:
                raise
            except (OSError, ValueError):
                pass
    if location is None:
        raise BrowserError("Workspace's browser connection host could not start.")
    connection = HostedConnection(location)
    exchange(location, {"operation": "connect", "client": connection.identity}, cancel, timeout=65)
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
