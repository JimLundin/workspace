"""The `Desktop` the assistant's features use, done with Windows calls and Qt."""

from collections.abc import Callable

from winapi import audio, clipboard, inputs, windows
lazy from desktop_ui.icons import State
lazy from desktop_ui.island_model import Job
lazy from desktop_ui.navigation import Order
lazy from desktop_ui.ui import Ui
lazy from protocol import MAGIC, Tool


class WinDesktop:
    __slots__ = ("mic", "mic_follower", "on_notify", "on_problem", "on_state", "owner", "ui")

    def __init__(  # noqa: PLR0913 - native owner, devices and event callbacks
        self,
        owner: int,
        mic: audio.Microphone,
        ui: Ui,
        *,
        on_state: Callable[[State], None],
        on_notify: Callable[[str, str], None],
        on_problem: Callable[[str], None],
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

    def type_text(self, text: str) -> None:
        inputs.type_text(text, MAGIC)

    def set_clipboard(self, text: str) -> None:
        if not clipboard.set_text(self.owner, text):
            raise OSError("The clipboard is busy. Try copying the transcript again.")

    # ---- the assistant's own windows ---------------------------------------------------

    def show_state(self, state: State) -> None:
        self.on_state(state)

    def busy(self, job: Job | None) -> None:
        self.ui.desktop_job(job)

    def notify(self, title: str, text: str) -> None:
        self.on_notify(title, text)

    def problem(self, message: str) -> None:
        self.on_problem(message)

    # ---- other programs' windows -------------------------------------------------------

    def navigate(self, order: Order) -> None:
        self.ui.navigate(order)

    def arrange(self, tool: Tool, *, target: int | None = None) -> None:
        hwnd = windows.foreground() if target is None else target
        if not hwnd:
            return
        match tool:
            case Tool.MINIMIZE:
                windows.show(hwnd, windows.SW_MINIMIZE)
            case _:
                raise AssertionError(f"{tool} doesn't arrange windows")
