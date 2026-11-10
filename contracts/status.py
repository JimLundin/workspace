"""What the assistant is doing, as the desktop shows it: the tray's state and the bar's quick job."""

from enum import Enum, auto


class State(Enum):
    """What the tray icon shows; its colour is the desktop's (`desktop_ui.icons.colour`)."""

    READY = auto()
    """Layout on; nothing running."""
    LAYOUT_OFF = auto()
    """The layout is switched off or not running; tools still work from the tray."""
    LISTENING = auto()
    RECORDING = auto()
    """A meeting is being recorded."""
    WORKING = auto()


TRANSCRIBING = sentinel("TRANSCRIBING")
"""Speech to text after dictation."""

TYPING = sentinel("TYPING")
"""Typing the transcript into the app that had the keyboard."""

type Job = TRANSCRIBING | TYPING
"""A quick job Workspace runs for you after a key press."""
