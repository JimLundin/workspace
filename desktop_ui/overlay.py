"""The learning overlay's state, placement and remembered preferences."""

import math
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path

from pydantic import StrictBool, TypeAdapter

from desktop_ui.keymap import PHYSICAL_NAMES, indicator_text
from keyboard.actions import Layer
from keyboard.physical import Scancode
from winapi.shapes import Point, Rect, Size


@dataclass(frozen=True, slots=True)
class Preference:
    enabled: StrictBool = field(kw_only=True)


_PREFERENCE = TypeAdapter(Preference)
_POSITION = TypeAdapter(Point)


def _read[T](path: Path, adapter: TypeAdapter[T]) -> T | None:
    try:
        return adapter.validate_json(path.read_bytes(), strict=True)
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


def load_enabled(path: Path) -> bool:
    """Start with the learning aid visible unless the user has hidden it."""
    preference = _read(path, _PREFERENCE)
    return preference.enabled if preference is not None else True


def save_enabled(*, enabled: bool, path: Path) -> None:
    _save(Preference(enabled=enabled), path, _PREFERENCE)


def load_position(path: Path) -> Point | None:
    """The drag handle's horizontal centre and top, in physical screen pixels."""
    return _read(path, _POSITION)


def save_position(position: Point, path: Path) -> None:
    _save(position, path, _POSITION)


def nearest_work_area(position: Point, areas: Sequence[Rect]) -> Rect:
    """The monitor under the handle, or the nearest remaining one after unplugging."""
    x, y = position.x, position.y

    def distance(area: Rect) -> int:
        return max(area.left - x, 0, x - (area.right - 1)) ** 2 + max(area.top - y, 0, y - (area.bottom - 1)) ** 2

    return min(areas, key=distance)


def fit_position(position: Point, size: Size, work: Rect) -> Point:
    """Keep the keyboard and handle on this monitor, with the handle always reachable."""
    visible_width = min(size.width, work.width)
    x = max(work.left + visible_width // 2, min(position.x, work.right - (visible_width - visible_width // 2)))
    y = max(work.top, min(position.y, work.bottom - size.height))
    return Point(x, y)


@dataclass(frozen=True, slots=True)
class KeyHighlights:
    """Held keys stay lit; a quick tap stays visible for at least the tap span it is given."""

    held: frozenset[Scancode] = frozenset()
    until: frozendict[Scancode, float] = frozendict()
    """When each recently pressed key may go dark."""

    def updated(self, held: frozenset[Scancode], now: float, tap: float) -> KeyHighlights:
        """The highlights once `held` are the keys down at `now`; a newly pressed key stays lit for at least `tap` seconds."""
        pressed = frozendict((key, now + tap) for key in held - self.held)
        kept = frozendict((key, until) for key, until in self.until.items() if key not in pressed and (key in held or until > now))
        return KeyHighlights(held, kept | pressed)

    def visible(self, now: float) -> frozenset[Scancode]:
        return self.held | frozenset(key for key, until in self.until.items() if key in self.held or until > now)

    def delay(self, now: float) -> int | None:
        """Milliseconds until the next released key goes dark; no polling while held."""
        deadlines = tuple(until for key, until in self.until.items() if key not in self.held and until > now)
        return max(1, math.ceil((min(deadlines) - now) * 1000)) if deadlines else None


@dataclass(frozen=True, slots=True)
class OverlayState:
    """An observation replaced by the UI owner after each layout event."""

    enabled: bool = field(default=True, kw_only=True)
    layout_on: bool = field(default=False, kw_only=True)
    layer: Layer = Layer.BASE
    caps_word: bool = field(default=False, kw_only=True)
    pressed: frozenset[Scancode] = frozenset()

    @property
    def visible(self) -> bool:
        return self.enabled and self.layout_on

    @property
    def title(self) -> str:
        """The layer indicator's words, led by BASE while no layer is held."""
        words = indicator_text(self.layer, caps_word=self.caps_word)
        if self.layer is not Layer.BASE and words is not None:
            return words
        return " · ".join(("BASE", *((words,) if words else ())))

    def set_layout(self, *, on: bool) -> OverlayState:
        return (
            replace(self, layout_on=True, pressed=frozenset())
            if on
            else replace(self, layout_on=False, pressed=frozenset(), layer=Layer.BASE, caps_word=False)
        )

    def indicate(self, layer: Layer, *, caps_word: bool) -> OverlayState:
        return replace(self, layer=layer, caps_word=caps_word)

    def key(self, scancode: Scancode, *, down: bool) -> OverlayState:
        if not scancode:
            return replace(self, pressed=frozenset())
        if self.layout_on and scancode in PHYSICAL_NAMES:
            pressed = self.pressed | {scancode} if down else self.pressed - {scancode}
            return replace(self, pressed=pressed)
        return self
