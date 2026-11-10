"""The laptop's own panel dims to its darkest with the screens while nobody is looking, and comes back with them.

`desktop_ui.away_screens` darkens this panel when the session locks and restores
it on unlock, with the external screens and the keyboard. It reads the
brightness the person set, turns it down to 0, and puts that level back. Only a
level this owner turned down is put back, and it is kept on disk until then, so
a Workspace restarted while locked still puts it back. A restore the panel
refuses, as with the lid closed, is tried again when the display changes.
"""

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
    """The built-in panel's brightness over WMI."""

    def level(self) -> Level | Unavailable:
        return panel_brightness.brightness()

    def set_level(self, level: int) -> Level | Unavailable:
        return panel_brightness.set_brightness(level)


@dataclass(frozen=True, slots=True)
class LaptopPanel:
    """The dimmed state while away; each change returns the owner's next state."""

    brightness: Brightness
    kept: Kept
    restore_to: int | None = None
    """The level the person set, while Workspace keeps the panel at 0."""

    @classmethod
    def resume(cls, brightness: Brightness, kept: Kept) -> LaptopPanel:
        """The panel as a previous Workspace may have left it: at 0, with the level to put back kept."""
        return cls(brightness, kept, kept.load())

    def darken(self) -> LaptopPanel:
        if self.restore_to is not None:
            return self  # Already down: reading again would remember 0 as the person's level.
        match self.brightness.level():
            case Level(value=0):
                return self  # Nothing to dim, and nothing to put back.
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
        """Puts the person's level back; kept for another try when refused, as when the lid closed meanwhile.

        Unlike the keyboard, a panel that comes back keeps the 0 it was left at."""
        if self.restore_to is None:
            return self
        match self.brightness.set_level(self.restore_to):
            case Level():
                self.kept.clear()
                return replace(self, restore_to=None)
            case Unavailable():
                return self
