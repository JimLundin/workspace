"""The learning overlay's state, placement and remembered preferences."""

import math
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Final

from pydantic import StrictBool, StrictInt, TypeAdapter

from assistant.keymap import PHYSICAL_NAMES
from miryoku.layout import Layer, Scancode
from usage import DIRECTORY
from winapi.shapes import Rect

PREFERENCE: Final = DIRECTORY / "overlay.json"
POSITION: Final = DIRECTORY / "overlay-position.json"
"""Position is written by the UI thread, independently of the tray preference."""


@dataclass(frozen=True, slots=True)
class Preference:
    enabled: StrictBool = field(kw_only=True)


@dataclass(frozen=True, slots=True)
class Position:
    x: StrictInt
    y: StrictInt


_PREFERENCE = TypeAdapter(Preference)
_POSITION = TypeAdapter(Position)


def _read[T](path: Path, adapter: TypeAdapter[T]) -> T | None:
    try:
        return adapter.validate_json(path.read_bytes())
    except OSError, ValueError:
        return None


def _save[T](data: T, path: Path, adapter: TypeAdapter[T]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    try:
        temporary.write_bytes(adapter.dump_json(data) + b"\n")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def load_enabled(path: Path = PREFERENCE) -> bool:
    """Start with the learning aid visible unless the user has hidden it."""
    preference = _read(path, _PREFERENCE)
    return preference.enabled if preference is not None else True


def save_enabled(*, enabled: bool, path: Path = PREFERENCE) -> None:
    _save(Preference(enabled=enabled), path, _PREFERENCE)


def load_position(path: Path = POSITION) -> tuple[int, int] | None:
    """The drag handle's horizontal centre and top, in physical screen pixels."""
    position = _read(path, _POSITION)
    return (position.x, position.y) if position is not None else None


def save_position(position: tuple[int, int], path: Path = POSITION) -> None:
    x, y = position
    _save(Position(x, y), path, _POSITION)


def nearest_work_area(position: tuple[int, int], areas: Sequence[Rect]) -> Rect:
    """The monitor under the handle, or the nearest remaining one after unplugging."""
    x, y = position

    def distance(area: Rect) -> int:
        return max(area.left - x, 0, x - (area.right - 1)) ** 2 + max(area.top - y, 0, y - (area.bottom - 1)) ** 2

    return min(areas, key=distance)


def fit_position(position: tuple[int, int], size: tuple[int, int], work: Rect) -> tuple[int, int]:
    """Keep the keyboard and handle on this monitor, with the handle always reachable."""
    x, y = position
    width, height = size
    visible_width = min(width, work.width)
    x = max(work.left + visible_width // 2, min(x, work.right - (visible_width - visible_width // 2)))
    y = max(work.top, min(y, work.bottom - height))
    return x, y


class KeyHighlights:
    """Held keys stay lit; a quick tap stays visible for at least 120 milliseconds."""

    __slots__ = ("_held", "_until")

    def __init__(self) -> None:
        self._held: frozenset[Scancode] = frozenset()
        self._until: dict[Scancode, float] = {}

    def update(self, held: frozenset[Scancode], now: float) -> None:
        for key in held - self._held:
            self._until[key] = now + 0.12
        self._held = held

    def visible(self, now: float) -> frozenset[Scancode]:
        self._until = {key: until for key, until in self._until.items() if key in self._held or until > now}
        return self._held | frozenset(self._until)

    def delay(self, now: float) -> int | None:
        """Milliseconds until the next released key goes dark; no polling while held."""
        deadlines = [until for key, until in self._until.items() if key not in self._held]
        return max(1, math.ceil((min(deadlines) - now) * 1000)) if deadlines else None

    def clear(self) -> None:
        self._held = frozenset()
        self._until.clear()


@dataclass(frozen=True, slots=True)
class OverlayState:
    """An observation replaced by the UI owner after each layout event."""

    enabled: bool = field(default=True, kw_only=True)
    layout_on: bool = field(default=False, kw_only=True)
    layer: Layer | None = None
    locked: bool = field(default=False, kw_only=True)
    caps_word: bool = field(default=False, kw_only=True)
    pressed: frozenset[Scancode] = frozenset()

    @property
    def visible(self) -> bool:
        return self.enabled and self.layout_on

    @property
    def title(self) -> str:
        parts = [self.layer.name if self.layer else "BASE"]
        if self.layer is not None and self.locked:
            parts.append("locked")
        if self.caps_word:
            parts.append("CAPS WORD")
        return " · ".join(parts)

    def set_layout(self, *, on: bool) -> OverlayState:
        return (
            replace(self, layout_on=True, pressed=frozenset())
            if on
            else replace(self, layout_on=False, pressed=frozenset(), layer=None, locked=False, caps_word=False)
        )

    def indicate(self, layer: Layer | None, *, locked: bool, caps_word: bool) -> OverlayState:
        return replace(self, layer=layer, locked=locked, caps_word=caps_word)

    def key(self, scancode: Scancode, *, down: bool) -> OverlayState:
        if not scancode:
            return replace(self, pressed=frozenset())
        if self.layout_on and scancode in PHYSICAL_NAMES:
            pressed = self.pressed | {scancode} if down else self.pressed - {scancode}
            return replace(self, pressed=pressed)
        return self
