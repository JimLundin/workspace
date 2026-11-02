"""A persistent canvas action: a filled capsule beside the floating card's text.

Qt owns hover, pressed and keyboard focus state. The button uses immediate
native feedback, with no animation or extra background work.
"""

lazy from PySide6 import QtCore, QtWidgets
lazy from PySide6.QtCore import Qt

from desktop_ui.components.bubble import Controls, action_face, action_style
from desktop_ui.vector_icons import icon


class CanvasJumpButton(QtWidgets.QPushButton):
    def __init__(self, parent: QtWidgets.QWidget, controls: Controls) -> None:
        super().__init__("", parent)
        self.setObjectName("canvasJump")
        self.setAccessibleName("Open on canvas")
        self.setToolTip("Open the related bubble on your work canvas")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFont(action_face(primary=False))
        self.setIconSize(QtCore.QSize(16, 16))
        self.setFixedSize(28, 28)
        self.recolor(controls)

    def recolor(self, controls: Controls) -> None:
        self.setIcon(icon("canvas", controls.ink.color))
        self.setStyleSheet(action_style(controls, primary=False) + "\nQPushButton#canvasJump { padding: 0; }")
