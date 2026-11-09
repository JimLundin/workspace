"""Colour carries meaning only: the tints a surface can take and the inks a part reads in."""

from enum import Enum, auto


class Tint(Enum):
    """A surface's meaning: none, or something that needs your attention."""

    NONE = auto()
    ATTENTION = auto()


class Tone(Enum):
    """Which ink a bar part reads in."""

    INK = auto()
    MICROPHONE = auto()
    LOW = auto()
