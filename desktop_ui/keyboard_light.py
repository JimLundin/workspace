"""The Charybdis's backlight goes dark with the screens while nobody is looking, and comes back with them.

`desktop_ui.away_screens` decides when (the lock, or idleness) and darkens and
restores this light at the same edges as the screens. The keyboard can't see a
lock or idleness, and locking doesn't suspend USB, so its own sleep handling
never fires. Workspace tells it over VIA instead: it reads the effect the person
set, turns the matrix off without saving, and puts that effect back. Nothing is
written to the keyboard's EEPROM, so a keyboard unplugged meanwhile comes back
lit as it was set.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from typing import Final, Protocol

from miryoku.firmware import FIRMWARE_KEYBOARD
from usage import Detail
from winapi import via

_VENDOR: Final = int(FIRMWARE_KEYBOARD[0].removeprefix("VID_"), 16)
_PRODUCT: Final = int(FIRMWARE_KEYBOARD[1].removeprefix("PID_"), 16)


class Backlight(Protocol):
    def effect(self) -> via.Effect | via.Absent: ...

    def set_effect(self, effect: int) -> via.Effect | via.Absent: ...


@dataclass(frozen=True, slots=True)
class ViaBacklight:
    """The attached Charybdis's RGB matrix over its VIA interface."""

    def effect(self) -> via.Effect | via.Absent:
        return self.send(via.effect_message(read=True))

    def set_effect(self, effect: int) -> via.Effect | via.Absent:
        return self.send(via.effect_message(read=False, effect=effect))

    def send(self, message: bytes) -> via.Effect | via.Absent:
        reply = via.exchange(_VENDOR, _PRODUCT, message)
        return via.Absent() if reply is None else via.effect_reply(message, reply)


@dataclass(frozen=True, slots=True)
class KeyboardLight:
    """The lights-off state while away; each change returns the owner's next state."""

    backlight: Backlight
    record: Callable[[str, Mapping[str, Detail]], None]
    restore_to: int | None = None
    """The effect the person set, while Workspace keeps the lights off."""

    def darken(self) -> KeyboardLight:
        if self.restore_to is not None:
            return self  # Already off: reading again would remember "off" as the person's setting.
        match self.backlight.effect():
            case via.Effect(value=0):
                # Already off, as after Workspace restarted while away: remembering
                # "off" would leave the keyboard dark once the person came back.
                return self
            case via.Effect(value=effect):
                match self.backlight.set_effect(0):
                    case via.Effect():
                        self.record("keyboard_light", {"lit": False, "ok": True})
                        return replace(self, restore_to=effect)
                    case via.Absent():
                        self.record("keyboard_light", {"lit": False, "ok": False})
                        return self
            case via.Absent():
                return self

    def restore(self) -> KeyboardLight:
        if self.restore_to is None:
            return self
        # Absent means it was unplugged meanwhile, and it starts lit from its saved setting.
        ok = self.backlight.set_effect(self.restore_to) != via.Absent()
        self.record("keyboard_light", {"lit": True, "ok": ok})
        return replace(self, restore_to=None)
