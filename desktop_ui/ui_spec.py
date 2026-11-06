"""The desktop's declarative specs: `desktop_ui/spec/*.toml`, validated into values.

The files are data the desktop reloads while it runs (`ui_spec_watch`); the keeper
restarts nothing when they change. Loading is all or nothing: a file that is
missing, malformed or out of range raises `SpecError` naming the file and the
field, and the caller keeps the spec it already has.
"""

import contextlib
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Final

from pydantic import ConfigDict, Field, TypeAdapter, ValidationError

from desktop_ui.island_menu import ControlsSpec, problems
from usage import DIRECTORY

SHIPPED: Final = Path(__file__).resolve().parent / "spec"
"""The specs installed with this copy of Workspace."""
KEPT: Final = DIRECTORY / "specs"
"""A copy of the last specs that validated: what the desktop starts with when an
edited spec no longer does."""

type Pixels = Annotated[float, Field(gt=0, le=4096)]
type Space = Annotated[float, Field(ge=0, le=4096)]
type Count = Annotated[int, Field(ge=1, le=256)]

_SPEC = ConfigDict(extra="forbid")


@dataclass(frozen=True, slots=True)
class Bar:
    top: Space
    edge: Space
    gap: Space
    radius: Space
    shadow: Space
    __pydantic_config__ = _SPEC


@dataclass(frozen=True, slots=True)
class Capsule:
    height: Pixels
    control: Pixels
    icon: Pixels
    spinner: Pixels
    dot: Pixels
    dots: Pixels
    wave_bars: Count
    part_gap: Space
    slot_gap: Space
    text_pad: Space
    icon_pad: Space
    __pydantic_config__ = _SPEC

    @property
    def inset(self) -> float:
        """A control at either end sits concentric with the capsule."""
        return (self.height - self.control) / 2

    @property
    def wave(self) -> float:
        """The microphone trace: two-pixel bars, two pixels apart."""
        return self.wave_bars * 4 - 2


@dataclass(frozen=True, slots=True)
class MenuGrid:
    width: Pixels
    radius: Space
    pad: Space
    head: Pixels
    track: Pixels
    gutter: Space
    __pydantic_config__ = _SPEC


@dataclass(frozen=True, slots=True)
class Detail:
    line: Pixels
    top: Space
    bottom: Space
    __pydantic_config__ = _SPEC


@dataclass(frozen=True, slots=True)
class Sizes:
    """`tokens.toml`: every size the island bar lays out and paints."""

    bar: Bar
    capsule: Capsule
    menu: MenuGrid
    detail: Detail
    __pydantic_config__ = _SPEC


class SpecError(Exception):
    """A spec file that can't be used; the message names the file and the field."""


@dataclass(frozen=True, slots=True)
class Specs:
    """Every spec the bar reads, loaded together so a reload applies all or none."""

    sizes: Sizes
    controls: ControlsSpec


_SIZES = TypeAdapter(Sizes)
_CONTROLS = TypeAdapter(ControlsSpec)


def _table(path: Path) -> dict[str, object]:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise SpecError(f"{path.name}: {error.strerror or error}") from error
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise SpecError(f"{path.name}: {error}") from error


def _invalid(path: Path, error: ValidationError) -> SpecError:
    first = error.errors()[0]
    field = ".".join(str(part) for part in first["loc"])
    return SpecError(f"{path.name}: {field}: {first['msg']}")


def load[T](path: Path, adapter: TypeAdapter[T]) -> T:
    """One spec file validated into its shape; `SpecError` names the file and the field."""
    try:
        return adapter.validate_python(_table(path))
    except ValidationError as error:
        raise _invalid(path, error) from error


BAR_FILES: Final = ("tokens.toml", "controls.toml")
"""The files the bar reads, which reload together."""


def sizes(folder: Path = SHIPPED) -> Sizes:
    path = folder / "tokens.toml"
    loaded = load(path, _SIZES)
    if loaded.capsule.control > loaded.capsule.height:
        raise SpecError(f"{path.name}: capsule.control: a control must fit its capsule's height")
    return loaded


def controls(folder: Path = SHIPPED) -> ControlsSpec:
    path = folder / "controls.toml"
    loaded = load(path, _CONTROLS)
    if found := problems(loaded):
        raise SpecError(f"{path.name}: {found[0]}")
    return loaded


def specs(folder: Path = SHIPPED) -> Specs:
    return Specs(sizes(folder), controls(folder))


def keep(folder: Path, names: tuple[str, ...], kept: Path = KEPT) -> None:
    """Copy spec files that just validated, so a later broken edit can't stop their reader."""
    kept.mkdir(parents=True, exist_ok=True)
    for name in names:
        partial = kept / (name + ".partial")
        partial.write_bytes((folder / name).read_bytes())
        partial.replace(kept / name)


def or_kept[T](read: Callable[[Path], T], names: tuple[str, ...], folder: Path, kept: Path) -> tuple[T, SpecError | None]:
    """`read` from the folder and keep a copy of `names`; when they don't validate,
    from the kept copy, with why."""
    try:
        loaded = read(folder)
    except SpecError as error:
        try:
            return read(kept), error
        except SpecError:
            raise error from None
    # The kept copy is a fallback; a data folder that can't be written costs only that.
    with contextlib.suppress(OSError):
        keep(folder, names, kept)
    return loaded, None


def starting_specs(folder: Path = SHIPPED, kept: Path = KEPT) -> tuple[Specs, SpecError | None]:
    """The bar's specs to start with and, when the folder's don't validate, why the kept copy is used."""
    return or_kept(specs, BAR_FILES, folder, kept)
