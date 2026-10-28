"""Small input decisions shared by Workspace's native desktop controls."""

from dataclasses import dataclass, field


@dataclass(slots=True)
class WindowsKeyTap:
    """A bare Windows-key release toggles the taskbar; chords and repeats do not."""

    held: set[int] = field(default_factory=set[int])
    armed: int | None = None

    def key(self, vk: int, down: bool) -> bool:
        if down:
            if vk in self.held:
                return False
            self.armed = vk if vk in (0x5B, 0x5C) and not self.held else None
            self.held.add(vk)
            return False
        self.held.discard(vk)
        toggle = vk == self.armed
        if vk in (0x5B, 0x5C):
            self.armed = None
        return toggle
