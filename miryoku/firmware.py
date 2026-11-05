"""Recognize the connected firmware keyboard and retain the user's laptop mode."""

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Final

from miryoku.layout import BASE, CELLS, TABLE, Key, Layer, TapHold, character
from protocol import App, Request, Tool

# Charybdis Nano (3x5) Splinky: match its USB identity, independent of port.
FIRMWARE_KEYBOARD: Final = ("VID_A8F8", "PID_1832")


def _base_key(cell: int) -> Key | None:
    match BASE.cells()[cell]:
        case Key() as key:
            return key
        case TapHold(tap=Key() as key):
            return key
        case _:
            return None


def _chord_keys() -> frozendict[Key, Request]:
    """Each Apps layer request by the base key at its place: one map for both keyboards."""
    keys: dict[Key, Request] = {}
    for cell in range(CELLS):
        match TABLE[Layer.APPS][cell]:
            case Tool() | App() as request if (key := _base_key(cell)) is not None:
                if key in keys:
                    raise ImportError(f"two Apps layer requests share the chord key {key.name}")
                keys[key] = request
            case Tool() | App():
                raise ImportError("an Apps layer request sits where the base layer has no key to chord")
            case _:
                pass
    return frozendict(keys)


def key_name(key: Key) -> str:
    """The chord key as it is written on the hints and in the README: a capital letter, or its name."""
    c = character(key, shifted=False)
    return "Space" if key is Key.SPACE else c.upper() if c else key.name.title()


_KEYS: Final = _chord_keys()
CHORDS: Final[frozendict[Request, str]] = frozendict({request: key_name(key) for key, request in _KEYS.items()})
"""Each request's key under the Apps hold: the laptop's Apps layer (hold the Delete thumb),
or the firmware keyboard's dedicated Apps thumb (`APPS_KEY`), with the key its keymap sends there."""

CHORD_KEYS: Final = frozendict({key.vk: request for key, request in _KEYS.items()})
"""Each request by its key's virtual key, which both keyboards share."""


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


APPS_KEY: Final = 0x87
"""F24, the virtual key the firmware keyboard's dedicated Apps thumb sends. Nothing else uses it."""


def shortcut(vk: int, *, apps_held: bool) -> Request | None:
    """The request a fresh firmware key press makes while the Apps thumb is held; other keys keep their meaning.

    Keys are matched by virtual key, so the host layout can't move them.
    """
    return CHORD_KEYS.get(vk) if apps_held else None


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
