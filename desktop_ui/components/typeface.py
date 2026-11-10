"""Workspace's typeface: Inter 4.1, loaded once into each Qt application.

Inter stands in for SF Pro, which Apple licenses for its platforms only. The static
Regular, Medium, SemiBold and Bold cuts ship in desktop_ui/fonts under the SIL Open
Font License 1.1 (desktop_ui/fonts/OFL.txt).
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import Final

lazy from PySide6 import QtGui

from desktop_ui.qt_runtime import prepare

prepare()

FAMILY: Final = "Inter"
FONTS: Final = Path(__file__).resolve().parent.parent / "fonts"
CUTS: Final = ("Inter-Regular.ttf", "Inter-Medium.ttf", "Inter-SemiBold.ttf", "Inter-Bold.ttf")


class Weight(IntEnum):
    """A cut, by its CSS weight."""

    REGULAR = 400
    MEDIUM = 500
    SEMIBOLD = 600


@dataclass(frozen=True, slots=True)
class Font:
    """Inter at a whole pixel size and weight."""

    pixels: int
    weight: Weight
    tabular: bool = field(default=False, kw_only=True)
    """Tabular digits, so a reading keeps its width as its digits change."""

    @property
    def css(self) -> str:
        return f"font-size: {self.pixels}px; font-weight: {int(self.weight)};"


@dataclass(frozen=True, slots=True, kw_only=True)
class TypeScale:
    """Every size and weight of text Workspace draws."""

    reading: Font
    """The bar's readings and labels."""
    strong: Font
    """A reading that leads, such as an activity card's title."""
    detail: Font
    """A quieter second line, caption or hint."""
    body: Font
    """Dialog and window text."""
    title: Font
    """A window's row titles, buttons and the layer indicator."""
    label: Font
    """Small controls: segmented choices and key-hint badges."""
    query: Font
    """The window switcher's search field."""
    keycap_name: Font
    """A key map key's physical name and hold, before the key map's scale."""
    keycap: Font
    """A key map key's legend..."""
    keycap_long: Font
    """...and one longer than five characters."""


def load(log: Callable[[str], None]) -> None:
    """Register the cuts with Qt's font database; views fall back to the system font if one is missing."""
    if FAMILY in QtGui.QFontDatabase.families():
        return
    for cut in CUTS:
        if QtGui.QFontDatabase.addApplicationFont(str(FONTS / cut)) < 0:
            log(f"Typeface {cut} unavailable; using the system font.")
