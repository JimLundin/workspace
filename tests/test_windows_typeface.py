"""Workspace's bundled typeface reaches Qt."""

import sys
import unittest

if sys.platform != "win32":
    raise unittest.SkipTest("Windows Qt font database")

lazy from PySide6 import QtGui

from desktop_ui.components import typeface
from desktop_ui.qt_runtime import prepare
from desktop_ui.qt_ui import application

prepare()


def test_bundled_typeface_resolves_every_shipped_weight() -> None:
    # Defect: the font files aren't shipped or their path is wrong, so every view
    # silently falls back to the system font.
    application()
    for weight in (QtGui.QFont.Weight.Normal, QtGui.QFont.Weight.Medium, QtGui.QFont.Weight.DemiBold, QtGui.QFont.Weight.Bold):
        font = QtGui.QFont(typeface.FAMILY, 12)
        font.setWeight(weight)
        info = QtGui.QFontInfo(font)
        assert info.family() == typeface.FAMILY and info.weight() == weight, f"{typeface.FAMILY} {weight} resolved to {info.family()} {info.weight()}"
