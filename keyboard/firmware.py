"""Recognize the connected firmware keyboard and retain the user's laptop mode."""

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Final

from keyboard import settings
from keyboard.actions import Layer, TapHold
from keyboard.bindings import action
from keyboard.board import Board
from keyboard.keys import Key
from protocol import App, Request, Tool


def _base_key(cell: int) -> Key | None:
    match action(Layer.BASE, cell):
        case Key() as key:
            return key
        case TapHold(tap=Key() as key):
            return key
        case _:
            return None


def _chord_keys() -> frozendict[Key, Request]:
    """Each Apps layer request by the base key at its place: one map for both keyboards."""
    requests = tuple((cell, request) for cell in range(Board.SIZE) if isinstance(request := action(Layer.APPS, cell), Tool | App))
    chorded = tuple((key, request) for cell, request in requests if (key := _base_key(cell)))
    if len(chorded) != len(requests):
        raise ImportError("an Apps layer request sits where the base layer has no key to chord")
    keys = frozendict(chorded)
    if len(keys) != len(chorded):
        repeated = next(key for index, (key, _) in enumerate(chorded) if key in frozendict(chorded[:index]))
        raise ImportError(f"two Apps layer requests share the chord key {repeated.name}")
    return keys


_IDENTITY: Final = (f"VID_{settings.FIRMWARE_VENDOR:04X}", f"PID_{settings.FIRMWARE_PRODUCT:04X}")
"""The firmware keyboard's USB identity as a HID device path writes it."""

_KEYS: Final = _chord_keys()
CHORDS: Final[frozendict[Request, str]] = frozendict({request: key.legend for key, request in _KEYS.items()})
"""Each request's key under the Apps hold: the laptop's Apps layer (hold the Delete thumb),
or the Charybdis's held Tab thumb (`APPS_KEY`), with the key its keymap sends there."""

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


def shortcut(vk: int, *, apps_held: bool) -> Request | None:
    """The request a fresh firmware key press makes while the Tab thumb holds Apps; other keys keep their meaning.

    Keys are matched by virtual key, so the host layout can't move them.
    """
    return CHORD_KEYS.get(vk) if apps_held else None


def connected(names: Iterable[str]) -> bool:
    """Ignore other HID keyboards, including the YubiKey and laptop controls."""
    for name in names:
        match name.upper().split("#"):
            case [r"\\?\HID", identity, *_]:
                match identity.split("&"):
                    case [vendor, product, *_] if (vendor, product) == _IDENTITY:
                        return True
                    case _:
                        pass
            case _:
                pass
    return False
