"""The `Desktop` the assistant's features use, done with Windows calls and Qt."""

import os
import subprocess
import time
from collections.abc import Callable
from typing import Final, Literal

from config import TERMINALS
from winapi import audio, clipboard, inputs, screen, windows
from winapi.shapes import Rect, Window
lazy from assistant.geometry import Shot, fit, half, to_monitor
lazy from assistant.icons import State
lazy from assistant.png import encode_png
lazy from assistant.textio import paste_text
lazy from assistant.tiling import GlazeWM
lazy from assistant.tiling_commands import GLOBAL_TILING, TILING_COMMANDS, WINDOW_COMMANDS
lazy from assistant.ui import AnswerWindow, Ui
lazy from protocol import MAGIC, Tool

_VK_CONTROL, _VK_C, _VK_V = 0xA2, 0x43, 0x56
_CLIPBOARD_WAIT_S: Final = 0.6
"""How long a program gets to put the selection on the clipboard after Ctrl+C."""
_PASTE_WAIT_S: Final = 0.4
"""How long a program gets to read the clipboard after Ctrl+V, before it's restored."""
_CREATE_NO_WINDOW: Final = 0x0800_0000


def _shortcut(vk: int) -> None:
    """Ctrl + a key, tagged so the layout lets it through."""
    keys = [
        inputs.KeyStroke(_VK_CONTROL, down=True),
        inputs.KeyStroke(vk, down=True),
        inputs.KeyStroke(vk, down=False),
        inputs.KeyStroke(_VK_CONTROL, down=False),
    ]
    inputs.send_keys(keys, MAGIC)


class WinDesktop:
    __slots__ = ("mic", "mic_follower", "on_notify", "on_problem", "on_state", "owner", "tiling", "ui")

    def __init__(
        self,
        owner: int,
        mic: audio.Microphone,
        ui: Ui,
        *,
        on_state: Callable[[State], None],
        on_notify: Callable[[str, str], None],
        on_problem: Callable[[str], None],
        tiling: GlazeWM | None = None,
    ) -> None:
        self.owner = owner
        """The assistant's window: it owns what we put on the clipboard."""
        self.mic = mic
        self.mic_follower = audio.DefaultFollower(mic)
        """Keeps dictation and the level meter on the current default capture device."""
        self.ui = ui
        self.on_state = on_state
        self.on_notify = on_notify
        self.on_problem = on_problem
        self.tiling = tiling

    # ---- the microphone ----------------------------------------------------------------

    def start_listening(self) -> str | None:
        if error := self.mic.start():
            return f"Can't open the microphone (Windows error {error}). Is microphone access on for desktop apps?"
        return None

    def stop_listening(self) -> bytes:
        return self.mic.stop()

    def close_microphone(self) -> None:
        self.mic_follower.close()
        self.mic.close()

    # ---- text in other programs --------------------------------------------------------

    def in_terminal(self) -> bool:
        return windows.exe(windows.foreground()) in TERMINALS

    def copy_selection(self) -> str | None:
        # In a terminal, Ctrl+C with nothing selected stops the running program: never send it there.
        if self.in_terminal():
            return None
        saved = clipboard.get_text(self.owner)
        before = clipboard.sequence()
        _shortcut(_VK_C)
        deadline = time.monotonic() + _CLIPBOARD_WAIT_S
        while clipboard.sequence() == before and time.monotonic() < deadline:
            time.sleep(0.02)
        if clipboard.sequence() == before:
            return None  # nothing was selected
        text = clipboard.get_text(self.owner)
        if saved is not None:
            clipboard.set_text(self.owner, saved)
        return text

    def paste(self, text: str) -> None:
        paste_text(self.owner, text, clipboard, lambda: _shortcut(_VK_V), lambda: time.sleep(_PASTE_WAIT_S))

    def type_text(self, text: str) -> None:
        inputs.type_text(text, MAGIC)

    def set_clipboard(self, text: str) -> None:
        if not clipboard.set_text(self.owner, text):
            raise OSError("The clipboard is busy. Try copying the transcript again.")

    # ---- the screen --------------------------------------------------------------------

    def choose_region(self) -> Rect | None:
        return self.ui.choose_region(screen.virtual_screen())

    def capture(self, area: Rect, longest: int) -> tuple[bytes, Shot]:
        width, height = fit(area.width, area.height, longest)
        return encode_png(width, height, screen.capture(area, width, height)), Shot(area, width, height)

    # ---- the assistant's own windows ---------------------------------------------------

    def prompt(self, title: str) -> str | None:
        return self.ui.prompt(title)

    def answer(self, title: str, follow_up: Callable[[str], None]) -> AnswerWindow:
        return self.ui.answer(title, follow_up)

    def show_state(self, state: State) -> None:
        self.on_state(state)

    def notify(self, title: str, text: str) -> None:
        self.on_notify(title, text)

    def problem(self, message: str) -> None:
        self.on_problem(message)

    # ---- other programs' windows -------------------------------------------------------

    def windows(self) -> list[Window]:
        return windows.windows()

    def foreground(self) -> int:
        return windows.foreground()

    def focus(self, handle: int) -> bool:
        return windows.focus(handle)

    def launch(self, command: str) -> None:
        try:
            os.startfile(command)  # as the Run dialog would: program names, paths, URLs, msteams:...
        except OSError:
            subprocess.Popen(["cmd", "/c", "start", "", command], creationflags=_CREATE_NO_WINDOW)

    def arrange(self, tool: Tool, *, target: int | None = None) -> None:
        hwnd = windows.foreground() if target is None else target
        if command := TILING_COMMANDS.get(tool):
            if self.tiling is None:
                raise OSError("Automatic tiling isn't available.")
            self.tiling.command(command, None if tool in GLOBAL_TILING else hwnd)
            return
        if not hwnd:
            return
        if self.tiling is not None and (command := WINDOW_COMMANDS.get(tool)) and self.tiling.arrange(command, hwnd):
            return
        match tool:
            case Tool.SNAP_LEFT | Tool.SNAP_RIGHT:
                if windows.is_maximized(hwnd):
                    windows.show(hwnd, windows.SW_RESTORE)
                side: Literal["left", "right"] = "left" if tool is Tool.SNAP_LEFT else "right"
                windows.move(hwnd, half(screen.monitor_of(hwnd).work, side, windows.outer_rect(hwnd), windows.visible_rect(hwnd)))
            case Tool.MAXIMIZE:
                windows.show(hwnd, windows.SW_RESTORE if windows.is_maximized(hwnd) else windows.SW_MAXIMIZE)
            case Tool.MINIMIZE:
                windows.show(hwnd, windows.SW_MINIMIZE)
            case Tool.NEXT_MONITOR:
                self.next_monitor(hwnd)
            case _:
                raise AssertionError(f"{tool} doesn't arrange windows")

    def next_monitor(self, hwnd: int) -> None:
        monitors = screen.monitors()
        if len(monitors) < 2:
            return
        current = screen.monitor_of(hwnd)
        index = next((i for i, m in enumerate(monitors) if m.area == current.area), 0)
        target = monitors[(index + 1) % len(monitors)]
        maximized = windows.is_maximized(hwnd)
        if maximized:
            windows.show(hwnd, windows.SW_RESTORE)
        windows.move(hwnd, to_monitor(windows.outer_rect(hwnd), current.work, target.work))
        if maximized:
            windows.show(hwnd, windows.SW_MAXIMIZE)
