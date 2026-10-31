"""A compact microphone and physical key legend, with instructions in its tooltip."""

lazy from PySide6 import QtGui, QtWidgets
lazy from PySide6.QtCore import Qt

from assistant.ui_components.appearance import MICROPHONE, Shade, scheme, tokens
from assistant.ui_components.widgets import glyph, row


class VoiceLegend(QtWidgets.QFrame):
    """Qt owns layout and the immediate painted feedback for live capture."""

    def __init__(self, key: str) -> None:
        super().__init__()
        self.pressed: bool = False
        theme = tokens(scheme())
        self.resting: QtGui.QPixmap = glyph("mic", theme.ink2)
        self.live: QtGui.QPixmap = glyph("mic.fill", Shade(MICROPHONE))
        self.setObjectName("voiceLegend")
        self.setAccessibleName("Speak to agent · " + key)
        self.setFixedHeight(32)
        layout = row(self)
        layout.setContentsMargins(8, 0, 6, 0)
        layout.setSpacing(7)
        self.microphone: QtWidgets.QLabel = QtWidgets.QLabel(self)
        self.microphone.setPixmap(self.resting)
        self.microphone.setFixedSize(16, 16)
        self.keycap: QtWidgets.QLabel = QtWidgets.QLabel(key, self)
        self.keycap.setObjectName("voiceKeycap")
        self.keycap.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.keycap.setFixedSize(22, 22)
        # A capsule from the kit: quiet at rest; while held, the microphone's privacy amber.
        self.setStyleSheet(
            "QFrame#voiceLegend { border: none; border-radius: 16px; background: transparent; }"
            f'QFrame#voiceLegend[pressed="true"] {{ background: {Shade(MICROPHONE, 0.16).css}; }}'
            f"QLabel#voiceKeycap {{ color: {theme.ink2.css}; background: {theme.fill.css}; border: 1px solid {theme.separator.css}; "
            f"border-bottom: 2px solid {theme.separator.css}; border-radius: 6px; font-size: 11px; font-weight: 600; }}"
            f'QLabel#voiceKeycap[pressed="true"] {{ color: #1c1c1e; background: {MICROPHONE}; '
            f"border-color: {MICROPHONE}; border-bottom-width: 1px; padding-top: 1px; }}"
        )
        layout.addWidget(self.microphone)
        layout.addWidget(self.keycap)

    def set_pressed(self, *, pressed: bool) -> None:
        # Native widgets must update in place. Capture observations arrive on
        # the Qt thread; repaint only on an edge, without animation or timers.
        if pressed == self.pressed:
            return
        self.pressed = pressed
        for widget in (self, self.keycap):
            widget.setProperty("pressed", pressed)
            widget.style().unpolish(widget)
            widget.style().polish(widget)
            widget.update()
        self.microphone.setPixmap(self.live if pressed else self.resting)
        self.setAccessibleDescription("Listening to agent speech" if pressed else "Hold the key to speak; release to send")
