"""Recognize the connected firmware keyboard and retain the user's laptop mode."""

from collections.abc import Collection, Iterable
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Final

from config import APPS
from protocol import Request, Tool

# Charybdis Nano (3x5) Splinky: match its USB identity, independent of port.
FIRMWARE_KEYBOARD: Final = ("VID_A8F8", "PID_1832")

_CHORD_LETTERS: Final[tuple[tuple[Request, str], ...]] = (
    # Right-hand letters, tapped while the left hand holds R S T, follow Miryoku's NAV positions.
    (Tool.FOCUS_LEFT, "N"), (Tool.FOCUS_DOWN, "E"), (Tool.FOCUS_UP, "I"), (Tool.FOCUS_RIGHT, "O"),
    # The top row J L U Y counts desktops 1 to 4 from the inner index finger.
    (Tool.DESKTOP_1, "J"), (Tool.DESKTOP_2, "L"), (Tool.DESKTOP_3, "U"), (Tool.DESKTOP_4, "Y"),
    (Tool.ZOOM, "M"),
    # Left-hand letters, tapped while the right hand holds N E I: config's apps along the top and home rows.
    *zip(APPS[:10], "QWFPBARSTG", strict=False),
    (Tool.PLACEMENT_PAUSE, "X"), (Tool.WINDOW_SWITCHER, "C"), (Tool.PLACE_NOW, "D"), (Tool.MINIMIZE, "V"),
)  # fmt: skip
CHORDS: Final[frozendict[Request, str]] = frozendict(_CHORD_LETTERS)
"""Ctrl+Alt+Shift + the letter asks Workspace for the request, from the firmware keyboard or the layout's home row mods."""

CHORD_KEYS: Final = frozendict({ord(letter): request for request, letter in CHORDS.items()})
"""Each chord's request by its letter's virtual key, which both keyboards share."""
_VOICE_KEYS: Final[frozendict[int, Request]] = frozendict({0x44: Tool.DICTATE, 0x47: Tool.AGENT_VOICE})
if len(CHORD_KEYS) != len(_CHORD_LETTERS) or not all("A" <= letter <= "Z" for letter in CHORDS.values()):
    raise ImportError("every firmware chord needs its own request and letter")


@dataclass(frozen=True, slots=True)
class FirmwareKeyboard:
    resume_layout: bool = field(kw_only=True)


@dataclass(frozen=True, slots=True)
class HeldShortcut:
    """A swallowed shortcut press whose release must finish its request."""

    identity: int
    request: Request


@dataclass(frozen=True, slots=True)
class ConsumedKey:
    """The request already ended; swallow repeats and the eventual physical up."""

    identity: int


type CapturedKey = HeldShortcut | ConsumedKey


MODIFIER_KEYS: Final = frozenset({0x1D, 0x11D, 0x38, 0x138, 0x2A, 0x36, 0x136, 0x15B, 0x15C})
"""Native identities of the Ctrl, Alt, Shift and Win keys that `modifiers` reads."""


class Modifiers(Enum):
    """The held native modifiers that select one of Workspace's firmware shortcuts."""

    VOICE = auto()
    """Ctrl+Shift: D holds dictation, G holds agent speech."""
    CHORD = auto()
    """Ctrl+Alt+Shift: a letter from `CHORDS`."""


def modifiers(held: Collection[int]) -> Modifiers | None:
    """Native identities include the extended bit, so either side's modifiers work.

    Win never takes part: Ctrl+Alt+Shift+Win is the Office key.
    """
    if not (0x1D in held or 0x11D in held) or 0x15B in held or 0x15C in held:
        return None
    # The observed Charybdis right Shift includes Windows' extended-key flag.
    if not (0x2A in held or 0x36 in held or 0x136 in held):
        return None
    return Modifiers.CHORD if 0x38 in held or 0x138 in held else Modifiers.VOICE


def shortcut(vk: int, held: Collection[int]) -> Request | None:
    """The request a fresh firmware key press makes; other keys keep their application meaning.

    Letters are matched by virtual key, so the host layout can't move them.
    """
    match modifiers(held):
        case Modifiers.VOICE:
            return _VOICE_KEYS.get(vk)
        case Modifiers.CHORD:
            return CHORD_KEYS.get(vk)
        case None:
            return None


def connected(names: Iterable[str]) -> bool:
    """Ignore other HID keyboards, including the YubiKey and laptop controls."""
    for name in names:
        match name.upper().split("#"):
            case [r"\\?\HID", identity, *_]:
                match identity.split("&"):
                    case [vendor, product, *_] if (vendor, product) == FIRMWARE_KEYBOARD:
                        return True
                    case _:
                        pass
            case _:
                pass
    return False
