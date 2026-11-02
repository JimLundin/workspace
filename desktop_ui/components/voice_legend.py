"""The canvas island's speak symbol: a microphone whose tooltip carries the instructions."""

lazy from PySide6 import QtCore, QtWidgets
lazy from PySide6.QtCore import Qt

from desktop_ui.components.appearance import MICROPHONE, Shade
from desktop_ui.components.canvas_look import CONTROL
from desktop_ui.components.widgets import row
from desktop_ui.vector_icons import icon


class VoiceLegend(QtWidgets.QFrame):
    """Qt owns layout and the immediate painted feedback for live capture.

    At rest the symbol takes the glass's ink; while listening it fills in the
    microphone's amber, as Apple's privacy indicator does.
    """

    def __init__(self, key: str, ink: Shade) -> None:
        super().__init__()
        self.pressed: bool = False
        self.ink: Shade = ink
        self.setObjectName("voiceLegend")
        self.setAccessibleName("Speak to agent · " + key)
        self.setFixedSize(CONTROL, CONTROL)
        layout = row(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.microphone: QtWidgets.QLabel = QtWidgets.QLabel(self)
        self.microphone.setPixmap(icon("mic", ink.color).pixmap(QtCore.QSize(16, 16)))
        self.microphone.setFixedSize(16, 16)
        layout.addWidget(self.microphone, 0, Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(
            f"QFrame#voiceLegend {{ border: none; border-radius: {CONTROL // 2}px; background: transparent; }}"
            f'QFrame#voiceLegend[pressed="true"] {{ background: {Shade(MICROPHONE, 0.2).css}; }}'
        )

    def set_pressed(self, *, pressed: bool) -> None:
        # Native widgets must update in place. Capture observations arrive on
        # the Qt thread; repaint only on an edge, without animation or timers.
        if pressed == self.pressed:
            return
        self.pressed = pressed
        self.setProperty("pressed", pressed)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()
        self.microphone.setPixmap(icon("mic.fill" if pressed else "mic", MICROPHONE if pressed else self.ink.color).pixmap(QtCore.QSize(16, 16)))
        self.setAccessibleDescription("Listening to agent speech" if pressed else "Hold the key to speak; release to send")
