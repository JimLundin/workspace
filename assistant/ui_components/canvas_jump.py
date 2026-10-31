"""A persistent canvas action in the floating card's visual language.

Qt owns hover, pressed and keyboard focus state. The button uses immediate
native feedback, with no animation or extra background work.
"""

lazy from PySide6 import QtCore, QtWidgets
lazy from PySide6.QtCore import Qt

from assistant.ui_components import typeface
from assistant.ui_components.appearance import GLASS_ACCENT, Ink, Shade
from assistant.ui_components.canvas_look import Role, face
from assistant.vector_icons import icon


class CanvasJumpButton(QtWidgets.QPushButton):
    def __init__(self, parent: QtWidgets.QWidget) -> None:
        super().__init__("Open on canvas", parent)
        self.setObjectName("canvasJump")
        self.setAccessibleName("Open on canvas")
        self.setToolTip("Open the related bubble on your work canvas")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFont(face(Role.CONTROL))
        self.setIconSize(QtCore.QSize(16, 16))
        self.recolor(Ink())

    def recolor(self, ink: Ink) -> None:
        # A filled capsule in the card's own ink, as the kit's buttons inside glass: never lilac or app-coloured.
        rest, hover, press = (Shade(ink.foreground, opacity).css for opacity in (0.10, 0.16, 0.22))
        self.setIcon(icon("canvas", ink.foreground))
        self.setStyleSheet(
            f"QPushButton#canvasJump {{ color: {ink.foreground}; background: {rest}; border: 2px solid transparent;"
            f" border-radius: 15px; padding: 4px 12px; text-align: left; font-family: '{typeface.FAMILY}'; font-size: 12px; font-weight: 500; }}"
            f" QPushButton#canvasJump:hover {{ background: {hover}; }}"
            f" QPushButton#canvasJump:pressed {{ background: {press}; }}"
            f" QPushButton#canvasJump:focus {{ border-color: {GLASS_ACCENT}; }}"
            f" QPushButton#canvasJump:disabled {{ color: {ink.secondary}; }}"
        )
