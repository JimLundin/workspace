from collections.abc import Iterable
from dataclasses import dataclass, field

from keyboard.layout import UsbIdentity
from protocol import Request


@dataclass(frozen=True, slots=True)
class FirmwareKeyboard:
    resume_layout: bool = field(kw_only=True)


@dataclass(frozen=True, slots=True)
class HeldShortcut:
    identity: int
    request: Request


@dataclass(frozen=True, slots=True)
class ConsumedKey:
    identity: int


type CapturedKey = HeldShortcut | ConsumedKey


def connected(names: Iterable[str], firmware: UsbIdentity) -> bool:
    expected = (f"VID_{firmware.vendor:04X}", f"PID_{firmware.product:04X}")
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
