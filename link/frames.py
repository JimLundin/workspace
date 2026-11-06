"""Length-prefixed frames on a stream socket, and an outbox that keeps only each state's latest."""

import socket
import threading
from collections import OrderedDict
from typing import Final

MAX_FRAME: Final = 64 * 1024 * 1024
"""Larger frames are refused: a peer that sends one is broken or hostile."""


def send(connection: socket.socket, payload: bytes) -> None:
    connection.sendall(len(payload).to_bytes(4, "big") + payload)


def _exactly(connection: socket.socket, size: int) -> bytes | None:
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = connection.recv(min(remaining, 1 << 20))
        if not chunk:
            return None
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def receive(connection: socket.socket) -> bytes | None:
    """The next frame; None once the peer has closed."""
    header = _exactly(connection, 4)
    if header is None:
        return None
    size = int.from_bytes(header, "big")
    if size > MAX_FRAME:
        raise OSError(f"A {size}-byte frame exceeds the link's limit.")
    return _exactly(connection, size)


class Outbox:
    """Frames waiting to be written, oldest first. A keyed frame replaces a waiting frame
    with the same key in its place, so a busy state never builds a backlog."""

    __slots__ = ("_closed", "_condition", "_counter", "_pending")

    def __init__(self) -> None:
        self._pending: OrderedDict[str | int, bytes] = OrderedDict()
        self._condition = threading.Condition()
        self._counter = 0
        self._closed = False

    def put(self, payload: bytes, key: str | None = None) -> None:
        with self._condition:
            if self._closed:
                return
            if key is None:
                self._counter += 1
                self._pending[self._counter] = payload
            else:
                self._pending[key] = payload
            self._condition.notify()

    def take(self) -> bytes | None:
        """The next frame, waiting for one; None once closed."""
        with self._condition:
            while not self._pending and not self._closed:
                self._condition.wait()
            if self._closed:
                return None
            _, payload = self._pending.popitem(last=False)
            return payload

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._condition.notify_all()
