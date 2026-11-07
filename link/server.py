"""The serving end of a link: one client at a time, its token proven, states replayed on connect.

The server listens on loopback and publishes its port and a per-boot token. A
client that connects sends the token first; a wrong token is closed without a
reply. A new client replaces the one before it. Keyed frames (states) replace
their waiting predecessor and the latest of each key is replayed to every client
that connects; unkeyed frames (events) are sent once, or dropped with no client.
"""

import contextlib
import hmac
import socket
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from link import frames
from link.endpoint import Endpoint, publish

HANDSHAKE_S: Final = 5.0
"""How long a connecting client has to prove its token."""


@dataclass(frozen=True, slots=True)
class _Connection:
    stream: socket.socket
    outbox: frames.Outbox = field(default_factory=frames.Outbox)

    def close(self) -> None:
        self.outbox.close()
        with contextlib.suppress(OSError):
            self.stream.shutdown(socket.SHUT_RDWR)
        self.stream.close()


class Server:
    __slots__ = ("_closed", "_current", "_listener", "_lock", "_receive", "_retained", "_thread", "token")

    def __init__(self, token: str, receive: Callable[[bytes], None], *, port: int = 0) -> None:
        self.token = token
        self._receive = receive
        self._listener = socket.create_server(("127.0.0.1", port))
        self._lock = threading.Lock()
        self._retained: frozendict[str, bytes] = frozendict()
        """The latest frame of each key, replaced whole under the lock, so a replay reads a fixed set."""
        self._current: _Connection | None = None
        self._closed = False
        self._thread = threading.Thread(target=self._accept, name="link server", daemon=True)

    @property
    def port(self) -> int:
        address: tuple[str, int] = self._listener.getsockname()
        return address[1]

    def start(self, published: Path | None = None) -> None:
        """Serve from now on; `published` is where clients find the port and token."""
        if published is not None:
            publish(published, Endpoint(self.port, self.token))
        self._thread.start()

    @property
    def connected(self) -> bool:
        with self._lock:
            return self._current is not None

    def send(self, payload: bytes, key: str | None = None) -> None:
        """Any thread: queue a frame for the client; a keyed frame is also kept for the next."""
        with self._lock:
            if key is not None:
                self._retained = frozendict({**self._retained, key: payload})
            current = self._current
        if current is not None:
            current.outbox.put(payload, key)

    def _accept(self) -> None:
        while not self._closed:
            try:
                connected, _ = self._listener.accept()
            except OSError:
                return
            threading.Thread(target=self._serve, args=(connected,), name="link client", daemon=True).start()

    def _serve(self, connected: socket.socket) -> None:
        connection = _Connection(connected)
        try:
            connected.settimeout(HANDSHAKE_S)
            offered = frames.receive(connected)
            if offered is None or not hmac.compare_digest(offered, self.token.encode()):
                return
            connected.settimeout(None)
            with self._lock:
                previous, self._current = self._current, connection
                for key, payload in self._retained.items():
                    connection.outbox.put(payload, key)
            if previous is not None:
                previous.close()
            threading.Thread(target=self._write, args=(connection,), name="link writer", daemon=True).start()
            while (frame := frames.receive(connected)) is not None:
                self._receive(frame)
        except OSError:
            pass
        finally:
            with self._lock:
                if self._current is connection:
                    self._current = None
            connection.close()

    @staticmethod
    def _write(connection: _Connection) -> None:
        with contextlib.suppress(OSError):
            while (payload := connection.outbox.take()) is not None:
                frames.send(connection.stream, payload)

    def close(self) -> None:
        self._closed = True
        with contextlib.suppress(OSError):
            self._listener.close()
        with self._lock:
            current, self._current = self._current, None
        if current is not None:
            current.close()
