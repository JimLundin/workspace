"""Workspace's typeface: Inter 4.1, loaded once into each Qt application.

Inter stands in for SF Pro, which Apple licenses for its platforms only. The static
Regular, Medium, SemiBold and Bold cuts ship in assistant/fonts under the SIL Open
Font License 1.1 (assistant/fonts/OFL.txt).
"""

from pathlib import Path
from typing import Final

lazy from PySide6 import QtGui

from assistant.qt_runtime import prepare
lazy from assistant.view_publication import log_view

prepare()

FAMILY: Final = "Inter"
FONTS: Final = Path(__file__).resolve().parent.parent / "fonts"
CUTS: Final = ("Inter-Regular.ttf", "Inter-Medium.ttf", "Inter-SemiBold.ttf", "Inter-Bold.ttf")


def load() -> None:
    """Register the cuts with Qt's font database; views fall back to the system font if one is missing."""
    if FAMILY in QtGui.QFontDatabase.families():
        return
    for cut in CUTS:
        if QtGui.QFontDatabase.addApplicationFont(str(FONTS / cut)) < 0:
            log_view(f"Typeface {cut} unavailable; using the system font.")
