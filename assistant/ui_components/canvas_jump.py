"""A persistent canvas action in the floating bubble's visual language.

Qt owns hover, pressed and keyboard focus state. The button uses immediate
native feedback, with no animation or extra background work.
"""

lazy from PySide6 import QtCore, QtWidgets
lazy from PySide6.QtCore import Qt

from assistant.ui_components.appearance import Ink
from assistant.ui_components.text import font
from assistant.vector_icons import icon


class CanvasJumpButton(QtWidgets.QPushButton):
    def __init__(self, parent: QtWidgets.QWidget) -> None:
        super().__init__("Open on canvas", parent)
        self.setObjectName("canvasJump")
        self.setAccessibleName("Open on canvas")
        self.setToolTip("Open the related bubble on your work canvas")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFont(font(9, bold=True))
        self.setIconSize(QtCore.QSize(16, 16))
        self.recolor(Ink())

    def recolor(self, ink: Ink) -> None:
        self.setIcon(icon("canvas", ink.foreground))
        self.setStyleSheet(
            f"QPushButton#canvasJump {{ color: {ink.foreground}; background: rgba(173,145,215,38); "
            f"border: 1px solid {ink.link}; border-radius: 11px; padding: 5px 12px; text-align: left; }} "
            "QPushButton#canvasJump:hover { background: rgba(173,145,215,65); } "
            "QPushButton#canvasJump:pressed { background: rgba(173,145,215,95); padding-top: 6px; padding-bottom: 4px; } "
            f"QPushButton#canvasJump:focus {{ border: 2px solid {ink.foreground}; padding: 4px 11px; }} "
            "QPushButton#canvasJump:disabled { color: #888888; border-color: #888888; }"
        )
