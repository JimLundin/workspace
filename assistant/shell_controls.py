"""Native taskbar ownership and a Windows-key observer, independent of any canvas."""

import os
import subprocess
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from assistant.shell_state import WindowsKeyTap
from protocol import LAYOUT_MAGIC
from winapi import desktop_shell, inputs, system

TASKBAR_TOGGLE = 0x8055


def toggle_taskbar(hwnd: int) -> None:
    system.post_message(hwnd, TASKBAR_TOGGLE, 0, 0)


@dataclass(frozen=True, slots=True)
class WindowsKeyEffects:
    read: Callable[[int], inputs.KeyEvent] = inputs.read_key_event
    forward: inputs.HookProc = inputs.call_next_hook
    toggle: Callable[[int], None] = toggle_taskbar


class WindowsKeyDispatch:
    """Own tap recognition while the hook adapter owns input observation and delivery."""

    __slots__ = ("effects", "hwnd", "state")

    def __init__(self, hwnd: int, effects: WindowsKeyEffects | None = None) -> None:
        self.hwnd = hwnd
        self.effects = effects if effects is not None else WindowsKeyEffects()
        self.state = WindowsKeyTap()

    def observe(self, code: int, wparam: int, lparam: int) -> int:
        if code == 0 and wparam in (system.WM_KEYDOWN, system.WM_KEYUP, system.WM_SYSKEYDOWN, system.WM_SYSKEYUP):
            key = self.effects.read(lparam)
            if not key.flags & inputs.LLKHF_INJECTED or key.extra == LAYOUT_MAGIC:
                down = wparam in (system.WM_KEYDOWN, system.WM_SYSKEYDOWN)
                self.state, toggle = self.state.key(key.vk, down=down)
                if toggle:
                    self.effects.toggle(self.hwnd)
        return self.effects.forward(code, wparam, lparam)


class WindowsKeyObserver:
    """Own the global keyboard hook on a message thread independent of Qt painting."""

    __slots__ = ("dispatch", "error", "hook", "ready", "stopped", "thread")

    def __init__(self, hwnd: int) -> None:
        self.dispatch = WindowsKeyDispatch(hwnd)
        self.hook: inputs.Hook | None = None
        self.error: OSError | None = None
        self.ready = threading.Event()
        self.stopped = threading.Event()
        self.thread = threading.Thread(target=self.run, name="taskbar keyboard messages", daemon=True)
        self.thread.start()
        self.wait_ready()

    def wait_ready(self) -> None:
        if not self.ready.wait(timeout=3):
            self.close()
            raise OSError("The taskbar keyboard observer did not become ready.")
        if self.error is not None:
            self.close()
            raise self.error

    def run(self) -> None:
        timer: int | None = None
        try:
            self.hook = inputs.set_keyboard_hook(self.dispatch.observe)
            if self.hook is None:
                raise OSError("Windows could not register the taskbar key. Its taskbar remains available.")
            timer = system.set_timer(50)
            if not timer:
                raise OSError("Windows could not start the taskbar keyboard message loop.")
            self.ready.set()
            for _ in system.messages():
                if self.stopped.is_set():
                    break
        except OSError as error:
            self.error = error
        finally:
            if timer is not None:
                system.kill_timer(timer)
            if self.hook is not None:
                inputs.remove_hook(self.hook)
                self.hook = None
            self.ready.set()

    def close(self) -> None:
        self.stopped.set()
        self.thread.join(timeout=3)
        if self.thread.is_alive():
            raise OSError("The taskbar keyboard observer did not release its hook.")


class TaskbarDesktop(Protocol):
    def taskbars(self) -> tuple[int, ...]: ...
    def visible(self, hwnd: int) -> bool: ...
    def taskbar_visible(self, hwnd: int, *, show: bool) -> None: ...


class RecoveryGuard(Protocol):
    def ready(self) -> bool: ...
    def poll(self) -> int | None: ...
    def close(self) -> None: ...


class NativeRecoveryGuard:
    """Own the recovery subprocess and its bounded readiness read."""

    __slots__ = ("process",)

    def __init__(self, process: subprocess.Popen[bytes]) -> None:
        self.process = process

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
            [str(python), "-m", "assistant.taskbar_guard", str(os.getpid())],
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
