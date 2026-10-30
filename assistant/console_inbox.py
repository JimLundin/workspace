"""An authenticated, local hook inbox. Pending answers survive UI changes, not application exit."""

import contextlib
import hmac
import json
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import cast

from assistant.console_requests import Answer, Command, Dismiss, Provider, Request, State, answered, hook_output, object_value, request, text

MAX_REQUESTS = 128


class ConsoleInbox:
    __slots__ = ("closed", "endpoint", "lock", "publish", "requests", "server", "thread", "timeout", "token", "waiters")

    def __init__(self, endpoint: Path, publish: Callable[[tuple[Request, ...]], None], *, timeout: float = 570) -> None:
        self.endpoint, self.publish, self.timeout = endpoint, publish, timeout
        self.lock = threading.RLock()
        self.closed = threading.Event()
        self.requests: dict[str, Request] = {}
        self.waiters: dict[str, threading.Event] = {}
        self.token = secrets.token_urlsafe(32)
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: object) -> None:
                pass  # Hook payloads may contain private messages or command arguments.

            def do_POST(self) -> None:
                if self.path != "/request" or not hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + owner.token):
                    self.send_error(403)
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= 64_000:
                        raise ValueError("Invalid hook payload size.")
                    data = object_value(cast(object, json.loads(self.rfile.read(length))))
                    provider = Provider(text(data.get("provider"), 64))
                    raw = data.get("event")
                    event = object_value(raw)
                    if event.get("hook_event_name") in ("Interrupt", "SessionEnd"):
                        owner.cancel_session(provider, text(event.get("session_id"), 512))
                        result: dict[str, object] = {}
                    else:
                        current = request(provider, raw, secrets.token_hex(16), time.time())
                        answer = owner.receive(current)
                        result = hook_output(provider, raw, answer)
                    output = json.dumps(result).encode("utf-8")
                except ValueError, TypeError:
                    self.send_error(400)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(output)))
                self.end_headers()
                with contextlib.suppress(BrokenPipeError, ConnectionResetError):
                    self.wfile.write(output)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.endpoint.parent.mkdir(parents=True, exist_ok=True)
        candidate = self.endpoint.with_suffix(".tmp")
        address = cast(object, self.server.socket.getsockname())
        if not isinstance(address, tuple):
            raise OSError("Console inbox has no valid local listener address.")
        elements = cast(tuple[object, ...], address)
        if len(elements) != 2 or type(elements[1]) is not int:
            raise OSError("Console inbox has no valid local listener address.")
        port = elements[1]
        configuration: dict[str, str] = {"url": f"http://127.0.0.1:{port}/request", "token": self.token}
        candidate.write_text(json.dumps(configuration), encoding="utf-8")
        candidate.chmod(0o600)
        candidate.replace(self.endpoint)
        self.thread = threading.Thread(target=self.server.serve_forever, name="Console inbox", daemon=True)
        self.thread.start()

    def changed(self) -> None:
        self.publish(tuple(self.requests.values()))

    def receive(self, current: Request) -> Request:
        with self.lock:
            if self.closed.is_set():
                return replace(current, state=State.EXPIRED)
            if len(self.requests) >= MAX_REQUESTS:
                retired = next((key for key, value in self.requests.items() if value.state is not State.WAITING and key not in self.waiters), None)
                if retired is None:
                    return replace(current, state=State.EXPIRED)
                self.requests.pop(retired)
            self.requests[current.identity] = current
            wait = threading.Event()
            if current.state is State.WAITING:
                self.waiters[current.identity] = wait
            self.changed()
        if current.state is State.WAITING:
            wait.wait(self.timeout)
            with self.lock:
                result = self.requests[current.identity]
                if result.state is State.WAITING:
                    result = self.requests[current.identity] = replace(result, state=State.EXPIRED)
                    self.changed()
                self.waiters.pop(current.identity, None)
                return result
        return current

    def command(self, command: Command) -> bool:
        with self.lock:
            if self.closed.is_set():
                return False
            current = self.requests.get(command.request)
            if current is None:
                return False
            match command:
                case Answer():
                    updated = answered(current, command)
                    if updated is None:
                        return False
                case Dismiss():
                    if current.state not in (State.WAITING, State.INFORMATION):
                        return False
                    updated = replace(current, state=State.EXPIRED if current.state is State.WAITING else State.ANSWERED)
            self.requests[current.identity] = updated
            if updated.state is not State.WAITING and (waiter := self.waiters.get(current.identity)) is not None:
                waiter.set()
            self.changed()
            return True

    def cancel_session(self, provider: Provider, session: str) -> None:
        with self.lock:
            for identity, current in tuple(self.requests.items()):
                if current.provider is provider and current.session == session and current.state is State.WAITING:
                    self.requests[identity] = replace(current, state=State.EXPIRED)
                    if (wait := self.waiters.get(identity)) is not None:
                        wait.set()
            self.changed()

    def close(self) -> None:
        self.closed.set()
        with self.lock:
            for identity, current in tuple(self.requests.items()):
                if current.state is State.WAITING:
                    self.requests[identity] = replace(current, state=State.EXPIRED)
            for waiter in self.waiters.values():
                waiter.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        with contextlib.suppress(FileNotFoundError):
            data = object_value(cast(object, json.loads(self.endpoint.read_text(encoding="utf-8"))))
            if data.get("token") == self.token:
                self.endpoint.unlink()
