"""The `Desktop` the assistant's features use: the microphone, typing and the clipboard on
Windows, and callbacks for what the desktop process should show."""

from collections.abc import Callable

from winapi import audio, clipboard, inputs
lazy from contracts.status import Job, State
lazy from protocol import MAGIC


class WinDesktop:
    __slots__ = ("mic", "mic_follower", "on_job", "on_notify", "on_problem", "on_state", "owner")

    def __init__(  # noqa: PLR0913 - native owner, devices and event callbacks
        self,
        owner: int,
        mic: audio.Microphone,
        *,
        on_state: Callable[[State], None],
        on_job: Callable[[Job | None], None],
        on_notify: Callable[[str, str], None],
        on_problem: Callable[[str], None],
    ) -> None:
        self.owner = owner
        """The assistant's window: it owns what we put on the clipboard."""
        self.mic = mic
        self.mic_follower = audio.DefaultFollower(mic)
        """Keeps dictation and the level meter on the current default capture device."""
        self.on_state = on_state
        self.on_job = on_job
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

    # ---- what the desktop shows --------------------------------------------------------

    def show_state(self, state: State) -> None:
        self.on_state(state)

    def busy(self, job: Job | None) -> None:
        self.on_job(job)

    def notify(self, title: str, text: str) -> None:
        self.on_notify(title, text)

    def problem(self, message: str) -> None:
        self.on_problem(message)
