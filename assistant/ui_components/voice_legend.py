"""A compact microphone and physical key legend, with instructions in its tooltip."""

lazy from PySide6 import QtCore, QtWidgets
lazy from PySide6.QtCore import Qt

from assistant.ui_components.widgets import row
from assistant.vector_icons import icon


class VoiceLegend(QtWidgets.QFrame):
    """Qt owns layout and the immediate painted feedback for live capture."""

    def __init__(self, key: str) -> None:
        super().__init__()
        self.pressed: bool = False
        self.setObjectName("voiceLegend")
        self.setAccessibleName("Speak to agent · " + key)
        self.setFixedHeight(32)
        layout = row(self)
        layout.setContentsMargins(7, 0, 7, 0)
        layout.setSpacing(7)
        self.microphone: QtWidgets.QLabel = QtWidgets.QLabel(self)
        self.microphone.setPixmap(icon("mic", "#d9c8f3").pixmap(QtCore.QSize(16, 16)))
        self.microphone.setFixedSize(16, 16)
        self.keycap: QtWidgets.QLabel = QtWidgets.QLabel(key, self)
        self.keycap.setObjectName("voiceKeycap")
        self.keycap.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.keycap.setFixedSize(22, 22)
        self.setStyleSheet(
            "QFrame#voiceLegend { border: 1px solid transparent; border-radius: 8px; }"
            'QFrame#voiceLegend[pressed="true"] { background: #49345e; border-color: #956cbf; }'
            "QLabel#voiceKeycap { color: #e6d8fa; background: #332a40; border: 1px solid #6e5b85; "
            "border-bottom: 2px solid #6e5b85; border-radius: 5px; font-size: 11px; font-weight: 600; }"
            'QLabel#voiceKeycap[pressed="true"] { color: #24132e; background: #d7b4ff; '
            "border-color: #ebd8ff; border-bottom-width: 1px; padding-top: 1px; }"
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
        self.microphone.setPixmap(icon("mic", "#ebd8ff" if pressed else "#d9c8f3").pixmap(QtCore.QSize(16, 16)))
        self.setAccessibleDescription("Listening to agent speech" if pressed else "Hold the key to speak; release to send")
