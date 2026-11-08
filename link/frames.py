"""Length-prefixed frames on a stream socket, and an outbox that keeps only each state's latest."""

import contextlib
import socket
import threading
from dataclasses import dataclass, field, replace
from typing import Final

from cell import Cell

MAX_FRAME: Final = 64 * 1024 * 1024
"""Larger frames are refused: a peer that sends one is broken or hostile."""


def send(connection: socket.socket, payload: bytes) -> None:
    connection.sendall(len(payload).to_bytes(4, "big") + payload)


def _exactly(connection: socket.socket, size: int) -> bytes | None:
    """`size` bytes, read straight into one buffer; None if the peer closes first."""
    buffer = bytearray(size)
    view = memoryview(buffer)
    filled = 0
    while filled < size:
        count = connection.recv_into(view[filled:], min(size - filled, 1 << 20))
        if not count:
            return None
        filled += count
    return bytes(buffer)


def receive(connection: socket.socket) -> bytes | None:
    """The next frame; None once the peer has closed."""
    header = _exactly(connection, 4)
    if header is None:
        return None
    size = int.from_bytes(header, "big")
    if size > MAX_FRAME:
        raise OSError(f"A {size}-byte frame exceeds the link's limit.")
    return _exactly(connection, size)


@dataclass(frozen=True, slots=True)
class _Queued:
    frames: frozendict[str | int, bytes] = frozendict()
    """Waiting frames, oldest first; an unkeyed frame is keyed by its arrival count."""
    arrivals: int = 0
    closed: bool = False


def _queued(queued: _Queued, payload: bytes, key: str | None) -> _Queued:
    if queued.closed:
        return queued
    if key is None:
        arrivals = queued.arrivals + 1
        return replace(queued, frames=frozendict({**queued.frames, arrivals: payload}), arrivals=arrivals)
    return replace(queued, frames=frozendict({**queued.frames, key: payload}))


@dataclass(frozen=True, slots=True)
class Outbox:
    """Frames waiting to be written, oldest first. A keyed frame replaces a waiting frame
    with the same key in its place, so a busy state never builds a backlog."""

    _queued: Cell[_Queued] = field(default_factory=lambda: Cell(_Queued()), init=False, repr=False)
    _condition: threading.Condition = field(default_factory=threading.Condition, init=False, repr=False)

    def put(self, payload: bytes, key: str | None = None) -> None:
        with self._condition:
            self._queued.update(lambda queued: _queued(queued, payload, key))
            self._condition.notify()

    def take(self) -> bytes | None:
        """The next frame, waiting for one; None once closed."""
        with self._condition:
            self._condition.wait_for(lambda: self._queued.get().frames or self._queued.get().closed)
            queued = self._queued.get()
            if queued.closed:
                return None
            first, payload = next(iter(queued.frames.items()))
            self._queued.set(replace(queued, frames=frozendict((key, value) for key, value in queued.frames.items() if key != first)))
            return payload

    def close(self) -> None:
        with self._condition:
            self._queued.update(lambda queued: replace(queued, closed=True))
            self._condition.notify_all()


def drain(outbox: Outbox, connection: socket.socket) -> None:
    """Send each queued payload until the outbox closes or the connection fails."""
    with contextlib.suppress(OSError):
        while (payload := outbox.take()) is not None:
            send(connection, payload)
