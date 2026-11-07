"""Native taskbar ownership, independent of any canvas. The layout observes the Windows key."""

import os
import subprocess
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

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


class TaskbarControl:
    """Hide Explorer's taskbars until toggled, and restore them on normal or abrupt exit."""

    __slots__ = ("closed", "desktop", "guard", "launch", "lock", "ready", "revealed")

    def __init__(self, desktop: TaskbarDesktop = desktop_shell, launch: Callable[[], RecoveryGuard] = launch_recovery_guard) -> None:
        self.closed = False
        self.desktop = desktop
        self.launch = launch
        self.guard: RecoveryGuard | None = None
        self.lock = threading.Lock()
        self.revealed = False
        self.ready = False

    def start(self) -> None:
        """The handshake runs on a worker. No taskbar is hidden before recovery is ready."""
        guard = self.launch()
        ready = guard.ready() and guard.poll() is None
        with self.lock:
            if ready and not self.closed:
                self.guard = guard
                self.ready = True
                return
        guard.close()
        if not ready:
            raise OSError("Independent taskbar recovery could not start; Windows taskbars remain available.")

    def toggle(self) -> None:
        self.revealed = not self.revealed
        self.enforce()

    def enforce(self) -> None:
        with self.lock:
            if self.closed or not self.ready:
                return
            if self.guard is None or self.guard.poll() is not None:
                self.ready = False
                for hwnd in self.desktop.taskbars():
                    self.desktop.taskbar_visible(hwnd, show=True)
                raise OSError("Taskbar recovery stopped; Windows taskbars have been restored.")
            for hwnd in self.desktop.taskbars():
                if self.desktop.visible(hwnd) != self.revealed:
                    self.desktop.taskbar_visible(hwnd, show=self.revealed)

    def close(self) -> None:
        with self.lock:
            self.closed = True
            owned, self.ready = self.ready, False
            guard, self.guard = self.guard, None
            if owned:
                for hwnd in self.desktop.taskbars():
                    self.desktop.taskbar_visible(hwnd, show=True)
        if guard is not None:
            guard.close()
