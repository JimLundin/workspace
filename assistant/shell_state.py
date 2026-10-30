"""Small input decisions shared by Workspace's native desktop controls."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class WindowsKeyTap:
    """A bare Windows-key release toggles the taskbar; chords and repeats do not."""

    held: frozenset[int] = frozenset()
    armed: int | None = None

    def key(self, vk: int, *, down: bool) -> tuple[WindowsKeyTap, bool]:
        """Return the next observation and toggle intent; dispatch owns replacement."""
        if down:
            if vk in self.held:
                return self, False
            armed = vk if vk in (0x5B, 0x5C) and not self.held else None
            return WindowsKeyTap(self.held | {vk}, armed), False
        toggle = vk == self.armed
        armed = None if vk in (0x5B, 0x5C) else self.armed
        return WindowsKeyTap(self.held - {vk}, armed), toggle
