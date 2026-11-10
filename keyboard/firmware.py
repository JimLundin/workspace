"""Recognize the connected firmware keyboard and retain the user's laptop mode."""

from collections.abc import Iterable
from dataclasses import dataclass, field

from keyboard.layout import UsbIdentity
from protocol import Request


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


def connected(names: Iterable[str], firmware: UsbIdentity) -> bool:
    """Ignore other HID keyboards, including the YubiKey and laptop controls."""
    expected = (f"VID_{firmware.vendor:04X}", f"PID_{firmware.product:04X}")  # as a HID device path writes it
    for name in names:
        match name.upper().split("#"):
            case [r"\\?\HID", identity, *_]:
                match identity.split("&"):
                    case [vendor, product, *_] if (vendor, product) == expected:
                        return True
                    case _:
                        pass
            case _:
                pass
    return False
