"""One retained tool-call row, with native status feedback and payload copying.

Qt owns the widgets and painted angle. Immutable invocation observations enter;
status changes retain the row and never create payload boxes or text documents.
"""

from collections.abc import Callable
from html import escape
from typing import assert_never

lazy from PySide6 import QtWidgets
lazy from PySide6.QtCore import QRect, QRectF, Qt
lazy from PySide6.QtGui import QPainter, QPaintEvent, QPen

from assistant.action_text import shortened
from assistant.qt_runtime import prepare
from assistant.tool_text import Call, State
from assistant.ui_components.appearance import DARK, Shade
from assistant.ui_components.text import META, STEP, TextInk, color, face, text_ink
from assistant.vector_icons import icon

prepare()

ROW_HEIGHT = 24
GLYPH = 16  # a step's status symbol, beside 12 px text as the kit's steps
TEXT_LEFT = GLYPH + 8
COPY_WIDTH = 46


def copy_text(text: str) -> None:
    QtWidgets.QApplication.clipboard().setText(text)


def status_color(state: State, ink: TextInk) -> Shade:
    match state:
        case State.SUCCEEDED:
            return ink.success
        case State.FAILED:
            return ink.error
        case State.RUNNING | State.CANCELLED:
            return ink.quiet
        case _:
            assert_never(state)


def symbol(state: State) -> str | None:
    """A finished step's Fluent symbol; a running step shows the spinner instead."""
    match state:
        case State.SUCCEEDED:
            return "check"
        case State.FAILED:
            return "close"
        case State.CANCELLED:
            return "minus"
        case State.RUNNING:
            return None
        case _:
            assert_never(state)


class StatusIcon(QtWidgets.QWidget):
    __slots__ = ("angle", "owner")

    def __init__(self, owner: ToolCall) -> None:
        super().__init__(owner)
        self.owner = owner
        # The conversation frame loop owns timestamps; Qt retains its last angle.
        self.angle: float = 90.0
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        state, ink = self.owner.call.state, self.owner.ink
        match symbol(state):
            case None:
                # The kit's spinner: a faint track with a turning head.
                ring = QRectF(2.5, 2.5, 11, 11)
                track = Shade(ink.ink.color, ink.ink.opacity * 0.32)
                painter.setPen(QPen(color(track), 1.8))
                painter.drawEllipse(ring)
                painter.setPen(QPen(color(ink.ink), 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                painter.drawArc(ring, round(self.angle * 16), 90 * 16)
            case str() as name:
                shade = status_color(state, ink)
                painter.setOpacity(shade.opacity)
                icon(name, shade.color).paint(painter, QRect(0, 0, GLYPH, GLYPH))


class ToolCall(QtWidgets.QWidget):
    __slots__ = ("call", "copy", "copy_action", "ink", "presented", "status", "title")

    def __init__(self, parent: QtWidgets.QWidget, call: Call, copy: Callable[[str], None] = copy_text) -> None:
        super().__init__(parent)
        self.copy_action, self.call, self.ink = copy, call, text_ink(DARK)
        self.presented: tuple[Call, int] | None = None
        self.setObjectName("toolCall-" + call.identity)
        self.status = StatusIcon(self)
        self.title = QtWidgets.QLabel(self)
        self.title.setTextFormat(Qt.TextFormat.PlainText)
        self.title.setFont(face(STEP))
        self.title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.copy = QtWidgets.QPushButton("Copy", self)
        self.copy.setFont(face(META, 500))
        self.copy.setCursor(Qt.CursorShape.PointingHandCursor)
        self.copy.clicked.connect(self.copy_payload)

    @property
    def identity(self) -> str:
        return self.call.identity

    def copy_payload(self) -> None:
        self.copy_action(self.call.copy_text)

    def present(self, call: Call, width: int) -> int:
        if self.presented == (call, width):
            return ROW_HEIGHT
        self.call = call
        self.resize(width, ROW_HEIGHT)
        self.copy.setVisible(bool(call.copy_text))
        copy_width = COPY_WIDTH + 4 if call.copy_text else 0
        text_width = max(1, width - TEXT_LEFT - copy_width)
        preview = call.result if call.state is State.FAILED else call.argument or call.result
        label = call.label + (" · " + shortened(" ".join(preview.split()), 240) if preview else "")
        self.title.setText(self.title.fontMetrics().elidedText(label, Qt.TextElideMode.ElideRight, text_width))
        self.status.setGeometry(0, (ROW_HEIGHT - GLYPH) // 2, GLYPH, GLYPH)
        self.title.setGeometry(TEXT_LEFT, 0, text_width, ROW_HEIGHT)
        self.copy.setGeometry(max(TEXT_LEFT, width - COPY_WIDTH), 1, COPY_WIDTH, ROW_HEIGHT - 2)
        self.setAccessibleName("Tool call: " + call.name)
        self.setAccessibleDescription(call.state.value)
        self.copy.setAccessibleName(("Copy arguments for " if call.argument else "Copy result for ") + call.name)
        detail = "\n".join(
            part for part in (call.name + " · " + call.state.value, shortened(call.argument, 800), shortened(call.result, 800)) if part
        )
        self.setToolTip("<pre>" + escape(detail) + "</pre>")
        self.recolor(self.ink)
        self.presented = (call, width)
        return ROW_HEIGHT

    def pulse(self, angle: float) -> None:
        if self.call.state is State.RUNNING:
            self.status.angle = angle
            self.status.update()

    def recolor(self, ink: TextInk) -> None:
        self.ink = ink
        hover, press = Shade(ink.ink.color, 0.08), Shade(ink.ink.color, 0.14)
        self.setStyleSheet(f"QWidget#{self.objectName()} {{ background: transparent; border: none; }}")
        self.title.setStyleSheet(f"background: transparent; border: none; padding: 0; margin: 0; color: {ink.quiet.css};")
        # A quiet row: Copy is plain at rest and fills under the pointer, as controls inside glass do.
        self.copy.setStyleSheet(
            f"QPushButton {{ background: transparent; border: none; border-radius: 11px; padding: 0; margin: 0; color: {ink.quiet.css}; }}"
            f"QPushButton:hover {{ background: {hover.css}; color: {ink.ink.css}; }}"
            f"QPushButton:pressed {{ background: {press.css}; }}"
            f"QPushButton:focus {{ outline: none; border: 2px solid {ink.link.css}; }}"
        )
        self.status.update()

    def toPlainText(self) -> str:
        return "\n".join(part for part in (self.call.label, self.call.state.value, self.call.name, self.call.argument, self.call.result) if part)
