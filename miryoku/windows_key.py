"""Recognize a bare Windows-key tap, which shows or hides the taskbar.

The layout's hook already sees every key, so it owns this observation. A
second low-level hook in the assistant would sit in front of the layout's
hook and stall every key whenever the assistant is busy; a stalled hook that
misses Windows' deadline lets the layout's swallowed keys through.
"""

from typing import Final

WINDOWS_KEYS: Final = frozenset({0x5B, 0x5C})


class WindowsKeyTap:
    """A bare Windows-key release is a tap; chords and repeats are not.

    The hook calls `key` for every key, so it updates its own state in place
    rather than allocating a record per event.
    """

    __slots__ = ("armed", "held")

    def __init__(self) -> None:
        self.held: set[int] = set()
        self.armed: int | None = None
        """The Windows key pressed with nothing else held, until another key joins it."""

    def key(self, vk: int, *, down: bool) -> bool:
        """Observe one key event; True when it completes a tap."""
        if down:
            if vk in self.held:
                return False
            self.armed = vk if vk in WINDOWS_KEYS and not self.held else None
            self.held.add(vk)
            return False
        self.held.discard(vk)
        tapped = vk == self.armed
        if vk in WINDOWS_KEYS:
            self.armed = None
        return tapped
