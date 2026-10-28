"""Native taskbar ownership and a Windows-key observer, independent of any canvas."""

import os
import subprocess
import sys
import threading
from pathlib import Path

from protocol import LAYOUT_MAGIC
from winapi import desktop_shell, inputs, system

from .shell_state import WindowsKeyTap

TASKBAR_TOGGLE = 0x8055


class WindowsKeyObserver:
    """Own the global keyboard hook on a message thread independent of Qt painting."""

    __slots__ = ("error", "hook", "hwnd", "ready", "state", "stopped", "thread")

    def __init__(self, hwnd: int) -> None:
        self.hwnd = hwnd
        self.state = WindowsKeyTap()
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
            self.hook = inputs.set_keyboard_hook(self.observe)
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

    def observe(self, code: int, wparam: int, lparam: int) -> int:
        if code == 0 and wparam in (system.WM_KEYDOWN, system.WM_KEYUP, system.WM_SYSKEYDOWN, system.WM_SYSKEYUP):
            key = inputs.read_key_event(lparam)
            if not key.flags & inputs.LLKHF_INJECTED or key.extra == LAYOUT_MAGIC:
                down = wparam in (system.WM_KEYDOWN, system.WM_SYSKEYDOWN)
                if self.state.key(key.vk, down):
                    system.post_message(self.hwnd, TASKBAR_TOGGLE, 0, 0)
        return inputs.call_next_hook(code, wparam, lparam)

    def close(self) -> None:
        self.stopped.set()
        self.thread.join(timeout=3)
        if self.thread.is_alive():
            raise OSError("The taskbar keyboard observer did not release its hook.")


class TaskbarControl:
    """Hide Explorer's taskbars until toggled, and restore them on normal or abrupt exit."""

    __slots__ = ("closed", "guard", "lock", "ready", "revealed")

    def __init__(self) -> None:
        self.closed = False
        self.guard: subprocess.Popen[bytes] | None = None
        self.lock = threading.Lock()
        self.revealed = False
        self.ready = False

    def start(self) -> None:
        """The handshake runs on a worker. No taskbar is hidden before recovery is ready."""
        python = Path(sys.executable).with_name("python.exe")
        guard = subprocess.Popen(
            [str(python), "-m", "assistant.taskbar_guard", str(os.getpid())],
            cwd=Path(__file__).resolve().parent.parent, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_BREAKAWAY_FROM_JOB,
        )
        response: list[bytes] = []
        received = threading.Event()
        def read() -> None:
            try:
                if guard.stdout is not None:
                    response.append(guard.stdout.readline(32))
            finally:
                received.set()
        threading.Thread(target=read, name="taskbar guard readiness", daemon=True).start()
        ready = received.wait(5) and response in ([b"ready\r\n"], [b"ready\n"]) and guard.poll() is None
        with self.lock:
            if ready and not self.closed:
                self.guard = guard
                self.ready = True
                return
        self._stop(guard)
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
                for hwnd in desktop_shell.taskbars():
                    desktop_shell.taskbar_visible(hwnd, show=True)
                raise OSError("Taskbar recovery stopped; Windows taskbars have been restored.")
            for hwnd in desktop_shell.taskbars():
                if desktop_shell.visible(hwnd) != self.revealed:
                    desktop_shell.taskbar_visible(hwnd, show=self.revealed)

    @staticmethod
    def _stop(guard: subprocess.Popen[bytes]) -> None:
        if guard.poll() is None:
            guard.terminate()
        guard.wait(timeout=3)
        if guard.stdout is not None:
            guard.stdout.close()

    def close(self) -> None:
        with self.lock:
            self.closed = True
            owned, self.ready = self.ready, False
            guard, self.guard = self.guard, None
            if owned:
                for hwnd in desktop_shell.taskbars():
                    desktop_shell.taskbar_visible(hwnd, show=True)
        if guard is not None:
            self._stop(guard)
