"""What the assistant is doing, as the desktop shows it: the tray's state and the bar's quick job."""

from enum import Enum, auto


class State(Enum):
    """What the tray icon shows. The value is its colour (red, green, blue)."""

    READY = (46, 160, 120)
    """Layout on; nothing running."""
    LAYOUT_OFF = (140, 140, 140)
    """The layout is switched off or not running; tools still work from the tray."""
    LISTENING = (220, 50, 50)
    RECORDING = (230, 64, 85)
    """A meeting is being recorded, including while the agent does other work."""
    WORKING = (235, 160, 30)
    AGENT = (60, 120, 230)
    """The agent is working on a task."""
    NEEDS_INPUT = (230, 185, 75)
    """A question is waiting in the agent panel."""


class Job(Enum):
    """A quick job Workspace runs for you after a key press."""

    TRANSCRIBING = auto()  # speech to text after dictation
