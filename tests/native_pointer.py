"""A real foreign window queries hit ownership on its own native message thread."""

import os
import socket
import subprocess
import sys
import time
import unittest
import uuid
from collections.abc import Callable, Generator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

if sys.platform != "win32":
    raise unittest.SkipTest("Windows pointer ownership")

from winapi import system, windows
from winapi.shapes import Rect

ROOT = Path(__file__).resolve().parent.parent


def receive(peer: socket.socket) -> str:
    # The socket reader owns this bounded partial frame until its immutable
    # observation is complete; only fixture status and HWNDs cross this channel.
    frame = bytearray()
    while len(frame) < 256:
        character = peer.recv(1)
        if not character:
            raise AssertionError("The native pointer fixture closed before replying.")
        if character == b"\n":
            return frame.decode("ascii")
        frame.extend(character)
    raise AssertionError("The native pointer fixture sent an unbounded response.")


@dataclass(frozen=True, slots=True)
class NativeWindow:
    handle: int
    process_id: int


@dataclass(frozen=True, slots=True)
class ForeignPointer:
    """Immutable identities of effects kept alive by the fixture context."""

    peer: socket.socket
    window: NativeWindow
    executor: ThreadPoolExecutor

    def sample(self, point: tuple[int, int], pump: Callable[[], None]) -> int:
        self.peer.sendall(f"hit:{point[0]}:{point[1]}\n".encode("ascii"))
        response = self.executor.submit(receive, self.peer)
        deadline = time.monotonic() + 6
        # A foreign hit query may ask Qt for WM_NCHITTEST. Keep Qt's owner
        # responsive instead of changing the result by blocking that thread.
        while not response.done() and time.monotonic() < deadline:
            pump()
            time.sleep(0.005)
        match response.result(timeout=1).split(":"):
            case ["hit", handle] if handle.isdecimal():
                return int(handle)
            case _:
                raise AssertionError("The native pointer fixture returned an invalid window.")


@contextmanager
def foreign_pointer(bounds: Rect) -> Generator[ForeignPointer]:
    title = "workspace native pointer " + uuid.uuid4().hex
    with socket.create_server(("127.0.0.1", 0)) as server:
        server.settimeout(10)
        address: object = server.getsockname()
        match address:
            case (str(), int() as port):
                pass
            case _:
                raise AssertionError("The native pointer fixture has no listening port.")
        process: subprocess.Popen[bytes] = subprocess.Popen(
            (
                sys.executable,
                "-m",
                "tests.native_pointer_target",
                str(port),
                title,
                str(bounds.left),
                str(bounds.top),
                str(bounds.right),
                str(bounds.bottom),
            ),
            cwd=ROOT,
            env=dict(os.environ, PYTHONPATH=str(ROOT)),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            peer, _address = server.accept()
            with peer, ThreadPoolExecutor(max_workers=1) as executor:
                peer.settimeout(6)
                match receive(peer).split(":"):
                    case ["ready", handle, identity] if handle.isdecimal() and identity.isdecimal():
                        window = NativeWindow(int(handle), int(identity))
                    case _:
                        raise AssertionError("The native pointer fixture returned an invalid identity.")
                assert windows.process_id(window.handle) == window.process_id != os.getpid()
                yield ForeignPointer(peer, window, executor)
        finally:
            if target_handle := windows.find(title):
                system.post_message(target_handle, system.WM_CLOSE, 0, 0)
            try:
                stdout, stderr = process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()  # Only this isolated fixture, never desktop Workspace.
                stdout, stderr = process.communicate(timeout=5)
        assert process.wait(timeout=5) == 0, (stdout + stderr).decode("utf-8", errors="replace")
