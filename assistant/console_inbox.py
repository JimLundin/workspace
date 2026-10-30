"""The local console hook inbox. Pending answers survive UI changes, not application exit."""

import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

from pydantic import TypeAdapter

from assistant.console_requests import Answer, Command, Dismiss, Provider, Request, State, answered, hook_output, object_value, request, text
from assistant.local_bridge import Contract, LocalBridge

MAX_REQUESTS = 128


@dataclass(frozen=True, slots=True)
class HookDelivery:
    """What `scripts/inbox_hook.py` posts: its provider and the CLI's hook event.

    The event stays an unvalidated observation until `console_requests.request`
    validates the supported shapes.
    """

    provider: Provider
    event: object


# `scripts/inbox_hook.py` runs without Workspace's dependencies and keeps its
# own copy of this contract: it reads the endpoint file, posts here and writes
# the reply verbatim as the CLI's hook output.
HOOK_BRIDGE: Contract[HookDelivery, dict[str, object]] = Contract("/request", TypeAdapter(HookDelivery), TypeAdapter(dict[str, object]))


class ConsoleInbox:
    __slots__ = ("bridge", "closed", "lock", "publish", "requests", "timeout", "waiters")

    def __init__(self, endpoint: Path, publish: Callable[[tuple[Request, ...]], None], *, timeout: float = 570) -> None:
        self.publish, self.timeout = publish, timeout
        self.lock = threading.RLock()
        self.closed = threading.Event()
        self.requests: dict[str, Request] = {}
        self.waiters: dict[str, threading.Event] = {}
        self.bridge = LocalBridge(endpoint, HOOK_BRIDGE, self.deliver)

    def deliver(self, delivery: HookDelivery) -> dict[str, object]:
        """Hold a waiting hook until it is answered, dismissed, cancelled or expired."""
        provider, event = delivery.provider, object_value(delivery.event)
        match event.get("hook_event_name"):
            case "Interrupt" | "SessionEnd":
                self.cancel_session(provider, text(event.get("session_id"), 512))
                return {}
            case _:
                return hook_output(provider, event, self.receive(request(provider, event, secrets.token_hex(16), time.time())))

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
        self.bridge.close()
