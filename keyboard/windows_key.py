"""Recognize a bare Windows-key tap, which shows or hides the taskbar.

The layout's hook already sees every key, so it owns this observation. A
second low-level hook in the assistant would sit in front of the layout's
hook and stall every key whenever the assistant is busy; a stalled hook that
misses Windows' deadline lets the layout's swallowed keys through.
"""

from dataclasses import dataclass
from typing import Final

WINDOWS_KEYS: Final = frozenset({0x5B, 0x5C})


@dataclass(frozen=True, slots=True)
class WindowsKeyTap:
    """A bare Windows-key release is a tap; chords and repeats are not."""

    held: frozenset[int] = frozenset()
    armed: int | None = None
    """The Windows key pressed with nothing else held, until another key joins it."""
    tapped: bool = False
    """The event just observed completed a tap."""

    def key(self, vk: int, *, down: bool) -> WindowsKeyTap:
        """Observe one key event."""
        if down:
            if vk in self.held:
                return WindowsKeyTap(self.held, self.armed) if self.tapped else self
            return WindowsKeyTap(self.held | {vk}, vk if vk in WINDOWS_KEYS and not self.held else None)
        return WindowsKeyTap(self.held - {vk}, None if vk in WINDOWS_KEYS else self.armed, tapped=vk == self.armed)
