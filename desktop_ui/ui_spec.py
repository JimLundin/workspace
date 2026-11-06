"""The desktop's declarative specs: `desktop_ui/spec/*.toml`, validated into values.

The files are data the desktop reloads while it runs (`ui_spec_watch`); the keeper
restarts nothing when they change. Loading is all or nothing: a file that is
missing, malformed or out of range raises `SpecError` naming the file and the
field, and the caller keeps the spec it already has.
"""

import contextlib
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Final

from pydantic import ConfigDict, Field, TypeAdapter, ValidationError

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


_SIZES = TypeAdapter(Sizes)


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


def sizes(folder: Path = SHIPPED) -> Sizes:
    path = folder / "tokens.toml"
    try:
        loaded = _SIZES.validate_python(_table(path))
    except ValidationError as error:
        raise _invalid(path, error) from error
    if loaded.capsule.control > loaded.capsule.height:
        raise SpecError(f"{path.name}: capsule.control: a control must fit its capsule's height")
    return loaded


def keep(folder: Path, kept: Path = KEPT) -> None:
    """Copy specs that just validated, so a later broken edit can't stop the desktop starting."""
    kept.mkdir(parents=True, exist_ok=True)
    for path in folder.glob("*.toml"):
        partial = kept / (path.name + ".partial")
        partial.write_bytes(path.read_bytes())
        partial.replace(kept / path.name)


def starting_sizes(folder: Path = SHIPPED, kept: Path = KEPT) -> tuple[Sizes, SpecError | None]:
    """The sizes to start with and, when the folder's don't validate, why the kept copy is used."""
    try:
        loaded = sizes(folder)
    except SpecError as error:
        try:
            return sizes(kept), error
        except SpecError:
            raise error from None
    # The kept copy is a fallback; a data folder that can't be written costs only that.
    with contextlib.suppress(OSError):
        keep(folder, kept)
    return loaded, None
