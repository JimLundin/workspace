from dataclasses import dataclass, replace
from typing import Protocol

from desktop_ui.kept import Kept
from winapi import panel_brightness
from winapi.panel_brightness import Level, Unavailable


class Brightness(Protocol):
    def level(self) -> Level | Unavailable: ...

    def set_level(self, level: int) -> Level | Unavailable: ...


@dataclass(frozen=True, slots=True)
class WmiBrightness:
    def level(self) -> Level | Unavailable:
        return panel_brightness.brightness()

    def set_level(self, level: int) -> Level | Unavailable:
        return panel_brightness.set_brightness(level)


@dataclass(frozen=True, slots=True)
class LaptopPanel:
    brightness: Brightness
    kept: Kept
    restore_to: int | None = None
    """The level the person set, while Workspace keeps the panel at 0."""

    @classmethod
    def resume(cls, brightness: Brightness, kept: Kept) -> LaptopPanel:
        return cls(brightness, kept, kept.load())

    def darken(self) -> LaptopPanel:
        if self.restore_to is not None:
            return self
        match self.brightness.level():
            case Level(value=0):
                return self
            case Level(value=level):
                match self.brightness.set_level(0):
                    case Level():
                        self.kept.save(level)
                        return replace(self, restore_to=level)
                    case Unavailable():
                        return self
            case Unavailable():
                return self

    def restore(self) -> LaptopPanel:
        if self.restore_to is None:
            return self
        match self.brightness.set_level(self.restore_to):
            case Level():
                self.kept.clear()
                return replace(self, restore_to=None)
            case Unavailable():
                return self
