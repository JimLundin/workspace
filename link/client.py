"""The connecting end of a link: finds the server's published endpoint, and again after it restarts.

The client keeps trying until it reaches the server, proves the token, then
reads frames until the server goes away, and starts over. `status` reports
each change, so the client's owner can say what is unavailable meanwhile.
Frames sent while disconnected are refused (`send` returns False), not queued:
a command meant for a server that is restarting would act on a stale view.
"""

import contextlib
import socket
import threading
from collections.abc import Callable
from enum import Enum, auto
from pathlib import Path
from typing import Final

from link import frames
from link.endpoint import read

RETRY_S: Final = 0.5


class Status(Enum):
    CONNECTED = auto()
    DISCONNECTED = auto()


class Client:
    __slots__ = ("_closed", "_endpoint", "_lock", "_outbox", "_receive", "_socket", "_status", "_thread")

    def __init__(self, endpoint: Path, receive: Callable[[bytes], None], status: Callable[[Status], None]) -> None:
        self._endpoint, self._receive, self._status = endpoint, receive, status
        self._lock = threading.Lock()
        self._outbox: frames.Outbox | None = None
        self._socket: socket.socket | None = None
        self._closed = threading.Event()
        self._thread = threading.Thread(target=self._run, name="link client", daemon=True)

    def start(self) -> None:
        self._thread.start()

    @property
    def connected(self) -> bool:
        with self._lock:
            return self._outbox is not None

    def send(self, payload: bytes) -> bool:
        """Any thread: queue a frame; False while no server is connected."""
        with self._lock:
            outbox = self._outbox
        if outbox is None:
            return False
        outbox.put(payload)
        return True

    def _run(self) -> None:
        while not self._closed.is_set():
            published = read(self._endpoint)
            if published is not None:
                with contextlib.suppress(OSError):
                    self._session(published.port, published.token)
            self._closed.wait(RETRY_S)

    def _session(self, port: int, token: str) -> None:
        with socket.create_connection(("127.0.0.1", port), timeout=RETRY_S * 4) as connected:
            connected.settimeout(None)
            frames.send(connected, token.encode())
            outbox = frames.Outbox()
            with self._lock:
                if self._closed.is_set():
                    return
                self._outbox, self._socket = outbox, connected
            writer = threading.Thread(target=self._write, args=(connected, outbox), name="link writer", daemon=True)
            writer.start()
            self._status(Status.CONNECTED)
            try:
                while (frame := frames.receive(connected)) is not None:
                    self._receive(frame)
            finally:
                with self._lock:
                    self._outbox, self._socket = None, None
                outbox.close()
                self._status(Status.DISCONNECTED)

    @staticmethod
    def _write(connected: socket.socket, outbox: frames.Outbox) -> None:
        with contextlib.suppress(OSError):
            while (payload := outbox.take()) is not None:
                frames.send(connected, payload)

    def close(self) -> None:
        self._closed.set()
        with self._lock:
            current = self._socket
        if current is not None:
            with contextlib.suppress(OSError):
                current.shutdown(socket.SHUT_RDWR)
        self._thread.join(timeout=5)
