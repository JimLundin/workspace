"""Native taskbar ownership: Explorer's taskbars stay hidden while the desktop runs."""

import os
import subprocess
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Protocol

from cell import Cell
from winapi import desktop_shell


class TaskbarDesktop(Protocol):
    def taskbars(self) -> tuple[int, ...]: ...
    def visible(self, hwnd: int) -> bool: ...
    def taskbar_visible(self, hwnd: int, *, show: bool) -> None: ...


class RecoveryGuard(Protocol):
    def ready(self) -> bool: ...
    def poll(self) -> int | None: ...
    def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class NativeRecoveryGuard:
    """Own the recovery subprocess and its bounded readiness read."""

    process: subprocess.Popen[bytes]

    def ready(self) -> bool:
        # One worker publishes the bounded pipe read before signalling readiness.
        response: list[bytes] = []
        received = threading.Event()

        def read() -> None:
            try:
                if self.process.stdout is not None:
                    response.append(self.process.stdout.readline(32))
            finally:
                received.set()

        threading.Thread(target=read, name="taskbar guard readiness", daemon=True).start()
        return received.wait(5) and response in ([b"ready\r\n"], [b"ready\n"])

    def poll(self) -> int | None:
        return self.process.poll()

    def close(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
        self.process.wait(timeout=3)
        if self.process.stdout is not None:
            self.process.stdout.close()


def launch_recovery_guard() -> RecoveryGuard:
    python = Path(sys.executable).with_name("python.exe")
    return NativeRecoveryGuard(
        subprocess.Popen(
            [str(python), "-m", "desktop_ui.taskbar_guard", str(os.getpid())],
            cwd=Path(__file__).resolve().parent.parent,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_BREAKAWAY_FROM_JOB,
        )
    )


@dataclass(frozen=True, slots=True)
class _Taskbars:
    ready: bool = False
    """Recovery is running, so the taskbars may be hidden."""
    closed: bool = False
    guard: RecoveryGuard | None = None


@dataclass(frozen=True, slots=True)
class TaskbarControl:
    """Keep Explorer's taskbars hidden, and restore them on normal or abrupt exit."""

    desktop: TaskbarDesktop = desktop_shell
    launch: Callable[[], RecoveryGuard] = launch_recovery_guard
    _state: Cell[_Taskbars] = field(default_factory=lambda: Cell(_Taskbars()), init=False, repr=False)
    """Replaced whole under the lock."""
    lock: threading.Lock = field(default_factory=threading.Lock, init=False)

    @property
    def ready(self) -> bool:
        return self._state.get().ready

    def start(self) -> None:
        """The handshake runs on a worker. No taskbar is hidden before recovery is ready."""
        guard = self.launch()
        ready = guard.ready() and guard.poll() is None
        with self.lock:
            if ready and not self._state.get().closed:
                self._state.update(lambda taskbars: replace(taskbars, guard=guard, ready=True))
                return
        guard.close()
        if not ready:
            raise OSError("Independent taskbar recovery could not start; Windows taskbars remain available.")

    def enforce(self) -> None:
        with self.lock:
            taskbars = self._state.get()
            if taskbars.closed or not taskbars.ready:
                return
            if taskbars.guard is None or taskbars.guard.poll() is not None:
                self._state.set(replace(taskbars, ready=False))
                for hwnd in self.desktop.taskbars():
                    self.desktop.taskbar_visible(hwnd, show=True)
                raise OSError("Taskbar recovery stopped; Windows taskbars have been restored.")
            for hwnd in self.desktop.taskbars():
                if self.desktop.visible(hwnd):
                    self.desktop.taskbar_visible(hwnd, show=False)

    def close(self) -> None:
        with self.lock:
            taskbars = self._state.get()
            self._state.set(replace(taskbars, closed=True, ready=False, guard=None))
            if taskbars.ready:
                for hwnd in self.desktop.taskbars():
                    self.desktop.taskbar_visible(hwnd, show=True)
        if taskbars.guard is not None:
            taskbars.guard.close()
