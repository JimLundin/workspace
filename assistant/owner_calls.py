"""One assistant thread executes volatile owner calls while the frontend polls.

Only the frontend submits calls, consumes replies and uses the pipe. The dispatch
thread re-reads run ownership immediately before invoking a desktop handler.
"""

import queue
import threading
import traceback
from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace

from automation import ipc
from automation.store import TaskStore
from automation.task import RunRef, owns

type CallKey = tuple[str, RunRef, str]


def request(message: ipc.Envelope) -> ipc.OwnerRequest:
    match message.payload:
        case ipc.OwnerRequest() as call:
            return call
        case _:
            raise ValueError("Only owner requests can be dispatched.")


def key(message: ipc.Envelope) -> CallKey:
    call = request(message)
    return message.epoch, call.run, call.request_id


@dataclass(frozen=True, slots=True)
class OwnerReply:
    message: ipc.Envelope
    result: ipc.OwnerResult
    error: str | None = None


class OwnerDispatcher:
    """Own bounded mailboxes and one handler thread until admitted calls settle.

    Queue and thread handles must remain mutable in this effect owner to hand
    calls between threads and confirm their exit. The frontend alone replaces
    immutable pending-key/cache snapshots; the handler thread never uses them.
    Two admitted calls (one executing, one queued) and 128 completed identities
    bound retention. Closing rejects queued work and waits for the active owner;
    the caller must retain its desktop owners until wait() confirms thread exit.
    """

    __slots__ = ("_calls", "_closing", "_finished", "_pending", "_replies", "_results", "_thread", "handle", "tasks", "wake")

    def __init__(self, handle: Callable[[ipc.OwnerCall], ipc.OwnerResult] | None, tasks: TaskStore, wake: threading.Event) -> None:
        self.handle, self.tasks, self.wake = handle, tasks, wake
        self._calls: queue.Queue[ipc.Envelope] = queue.Queue(maxsize=1)
        self._replies: queue.Queue[OwnerReply] = queue.Queue(maxsize=2)
        self._closing, self._finished = threading.Event(), threading.Event()
        self._pending: frozenset[CallKey] = frozenset()
        self._results: tuple[OwnerReply, ...] = ()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="desktop owner calls", daemon=True)
            self._thread.start()

    def _remember(self, reply: OwnerReply) -> OwnerReply:
        self._results = (*self._results[-127:], reply)
        return reply

    def submit(self, message: ipc.Envelope) -> OwnerReply | None:
        identity = key(message)
        for reply in self._results:
            if key(reply.message) == identity:
                return replace(reply, message=message, error=None)
        if identity in self._pending:
            return None
        if self._closing.is_set():
            return self._remember(OwnerReply(message, ipc.Failed("The assistant owner is stopping.")))
        if len(self._pending) >= 2:
            return self._remember(OwnerReply(message, ipc.Failed("The assistant owner is busy; inspect its current state before trying again.")))
        self._pending = self._pending | {identity}
        try:
            self._calls.put_nowait(message)
        except queue.Full:
            self._pending = self._pending - {identity}
            return self._remember(OwnerReply(message, ipc.Failed("The assistant owner is busy; inspect its current state before trying again.")))
        return None

    def ready(self) -> Iterator[OwnerReply]:
        while True:
            try:
                reply = self._replies.get_nowait()
            except queue.Empty:
                return
            self._pending = self._pending - {key(reply.message)}
            yield self._remember(reply)

    @property
    def pending(self) -> bool:
        return bool(self._pending)

    def _run(self) -> None:
        try:
            while True:
                try:
                    message = self._calls.get(timeout=0.1)
                except queue.Empty:
                    if self._closing.is_set():
                        return
                    continue
                error: str | None = None
                try:
                    call = request(message)
                    task = self.tasks.get(call.run.task_id)
                    if self._closing.is_set():
                        result: ipc.OwnerResult = ipc.Failed("The assistant owner is stopping.")
                    elif task is None or not owns(task, call.run):
                        result = ipc.Failed("This work run no longer owns the owner request.")
                    elif self.handle is None:
                        result = ipc.Failed("The assistant owner is unavailable.")
                    else:
                        result = self.handle(call.call)
                except Exception:
                    error = traceback.format_exc()
                    result = ipc.Failed("The owner operation failed; see the assistant log and inspect its current state.")
                self._replies.put(OwnerReply(message, result, error))
                self.wake.set()
        finally:
            self._finished.set()
            self.wake.set()

    def close(self) -> None:
        self._closing.set()
        if self._thread is None:
            self._finished.set()

    def wait(self, timeout: float | None = None) -> bool:
        return self._finished.wait(timeout)
