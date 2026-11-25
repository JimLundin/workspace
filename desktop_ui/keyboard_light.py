from dataclasses import dataclass, replace
from typing import Protocol

from desktop_ui.kept import Kept
from keyboard.layout import UsbIdentity
from winapi import via


class Backlight(Protocol):
    def effect(self) -> via.Effect | via.Absent: ...

    def set_effect(self, effect: int) -> via.Effect | via.Absent: ...


@dataclass(frozen=True, slots=True)
class ViaBacklight:
    firmware: UsbIdentity

    def effect(self) -> via.Effect | via.Absent:
        return self.send(via.effect_message(read=True))

    def set_effect(self, effect: int) -> via.Effect | via.Absent:
        return self.send(via.effect_message(read=False, effect=effect))

    def send(self, message: bytes) -> via.Effect | via.Absent:
        reply = via.exchange(
            self.firmware.vendor, self.firmware.product, message
        )
        return (
            via.Absent() if reply is None else via.effect_reply(message, reply)
        )


@dataclass(frozen=True, slots=True)
class KeyboardLight:
    backlight: Backlight
    kept: Kept
    restore_to: int | None = None
    """The effect the person set, while Workspace keeps the lights off."""

    @classmethod
    def resume(cls, backlight: Backlight, kept: Kept) -> KeyboardLight:
        return cls(backlight, kept, kept.load())

    def darken(self) -> KeyboardLight:
        if self.restore_to is not None:
            return self
        match self.backlight.effect():
            case via.Effect(value=0):
                return self
            case via.Effect(value=effect):
                match self.backlight.set_effect(0):
                    case via.Effect():
                        self.kept.save(effect)
                        return replace(self, restore_to=effect)
                    case via.Absent():
                        return self
            case via.Absent():
                return self

    def restore(self) -> KeyboardLight:
        if self.restore_to is None:
            return self
        self.backlight.set_effect(self.restore_to)
        self.kept.clear()
        return replace(self, restore_to=None)
