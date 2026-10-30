"""Recognize the connected firmware keyboard and retain the user's laptop mode."""

from collections.abc import Collection, Iterable
from dataclasses import dataclass, field
from typing import Final

from protocol import Tool

# Charybdis Nano (3x5) Splinky: match its USB identity, independent of port.
FIRMWARE_KEYBOARD: Final = ("VID_A8F8", "PID_1832")


@dataclass(frozen=True, slots=True)
class FirmwareKeyboard:
    resume_layout: bool = field(kw_only=True)


@dataclass(frozen=True, slots=True)
class VoiceShortcut:
    """A swallowed voice key press whose release must finish the voice request."""

    identity: int
    tool: Tool


@dataclass(frozen=True, slots=True)
class ConsumedKey:
    """Recording already ended; swallow repeats and the eventual physical up."""

    identity: int


type CapturedKey = VoiceShortcut | ConsumedKey


def voice_tool(vk: int, held: Collection[int]) -> Tool | None:
    """Ctrl+Alt+D/G uses plain Miryoku letters and opposite-hand home-row mods.

    Native identities include the extended bit, so either side's Ctrl/Alt works.
    Shift/Win chords retain their application meaning. Plain voice keys stay native.
    """
    match vk:
        case 0x44:
            tool = Tool.DICTATE
        case 0x47:
            tool = Tool.AGENT_VOICE
        case _:
            return None
    if not (0x1D in held or 0x11D in held) or not (0x38 in held or 0x138 in held):
        return None
    if any(identity in held for identity in (0x2A, 0x36, 0x15B, 0x15C)):
        return None
    return tool


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
