"""The loopback link between the desktop and the assistant, over real sockets."""

import threading
import time
from collections.abc import Callable
from pathlib import Path

from link.client import Client, Status
from link.endpoint import Endpoint, publish
from link.server import Server


def until(condition: Callable[[], bool], seconds: float = 5.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return False


class Peer:
    """What one end received, in order, and its link's status changes."""

    def __init__(self) -> None:
        self.frames: list[bytes] = []
        self.statuses: list[Status] = []
        self.lock = threading.Lock()

    def receive(self, frame: bytes) -> None:
        with self.lock:
            self.frames.append(frame)

    def status(self, status: Status) -> None:
        with self.lock:
            self.statuses.append(status)


def test_a_connecting_desktop_gets_the_latest_states_then_events_and_its_commands_arrive(tmp_path: Path) -> None:
    # Defects: a desktop that connects late sees no current state, sees every stale
    # state in turn, misses an event, or its commands never reach the assistant.
    endpoint = tmp_path / "endpoint-assistant"
    assistant, desktop = Peer(), Peer()
    server = Server.listen("boot-token", assistant.receive)
    server.send(b"session 1", "session")
    server.send(b"session 2", "session")
    server.send(b"dropped event")  # No desktop yet: an event is not kept.
    server.start(endpoint)
    client = Client(endpoint, desktop.receive, desktop.status)
    client.start()
    try:
        assert until(lambda: desktop.frames == [b"session 2"])
        server.send(b"notice")
        assert until(lambda: desktop.frames == [b"session 2", b"notice"])
        assert client.send(b"use tool")
        assert until(lambda: assistant.frames == [b"use tool"])
    finally:
        client.close()
        server.close()


def test_a_wrong_token_is_closed_without_a_reply(tmp_path: Path) -> None:
    # Defect: any local program that finds the port drives the assistant.
    endpoint = tmp_path / "endpoint-assistant"
    assistant, intruder = Peer(), Peer()
    server = Server.listen("boot-token", assistant.receive)
    server.send(b"session", "session")
    server.start(None)
    publish(endpoint, Endpoint(server.port, "guessed"))
    client = Client(endpoint, intruder.receive, intruder.status)
    client.start()
    try:
        assert until(lambda: Status.DISCONNECTED in intruder.statuses), "The server kept a client with the wrong token"
        client.send(b"use tool")
        assert not until(lambda: bool(assistant.frames) or server.connected, seconds=0.1)
        assert intruder.frames == []
    finally:
        client.close()
        server.close()


def test_the_desktop_reconnects_when_the_assistant_restarts(tmp_path: Path) -> None:
    # Defect: after the assistant restarts the desktop stays disconnected, or keeps
    # sending into the closed connection, so its commands vanish.
    endpoint = tmp_path / "endpoint-assistant"
    first, desktop = Peer(), Peer()
    server = Server.listen("first-boot", first.receive)
    server.send(b"before", "session")
    server.start(endpoint)
    client = Client(endpoint, desktop.receive, desktop.status)
    client.start()
    try:
        assert until(lambda: desktop.statuses == [Status.CONNECTED] and desktop.frames == [b"before"])
        server.close()
        assert until(lambda: desktop.statuses == [Status.CONNECTED, Status.DISCONNECTED])
        assert until(lambda: not client.send(b"lost"))
        second = Peer()
        restarted = Server.listen("second-boot", second.receive)
        restarted.send(b"after", "session")
        restarted.start(endpoint)
        try:
            assert until(lambda: desktop.statuses[-1:] == [Status.CONNECTED] and b"after" in desktop.frames)
            assert client.send(b"again")
            assert until(lambda: second.frames == [b"again"])
        finally:
            restarted.close()
    finally:
        client.close()
        server.close()
