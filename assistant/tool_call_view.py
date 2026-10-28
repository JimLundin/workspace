"""One retained tool-call row, with native status feedback and payload copying.

Qt owns the widgets and painted angle. Immutable invocation observations enter;
status changes retain the row and never create payload boxes or text documents.
"""

from collections.abc import Callable
from html import escape
from typing import assert_never

lazy from PySide6 import QtWidgets
lazy from PySide6.QtCore import QRectF, Qt
lazy from PySide6.QtGui import QColor, QPainter, QPaintEvent, QPen

from assistant.action_text import shortened
from assistant.qt_runtime import prepare
from assistant.qt_text import font
from assistant.toast_style import Ink
from assistant.tool_text import Call, State

prepare()

ROW_HEIGHT = 28


def copy_text(text: str) -> None:
    QtWidgets.QApplication.clipboard().setText(text)


def status_color(state: State, ink: Ink) -> str:
    # High contrast supplies one foreground for every ink role; retain it.
    if ink.foreground == ink.secondary == ink.error:
        return ink.foreground
    match state:
        case State.SUCCEEDED:
            return '#76d49a'
        case State.FAILED:
            return ink.error
        case State.RUNNING | State.CANCELLED:
            return ink.secondary
        case _:
            assert_never(state)


class StatusIcon(QtWidgets.QWidget):
    __slots__ = ('angle', 'owner')

    def __init__(self, owner: ToolCall) -> None:
        super().__init__(owner)
        self.owner = owner
        # The conversation frame loop owns timestamps; Qt retains its last angle.
        self.angle: float = 90.0
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(status_color(self.owner.call.state, self.owner.ink)), 1.7,
                            Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        match self.owner.call.state:
            case State.RUNNING:
                painter.drawArc(QRectF(2, 2, 12, 12), round(self.angle * 16), 240 * 16)
            case State.SUCCEEDED:
                painter.drawLine(3, 8, 7, 12)
                painter.drawLine(7, 12, 13, 4)
            case State.FAILED:
                painter.drawLine(4, 4, 12, 12)
                painter.drawLine(12, 4, 4, 12)
            case State.CANCELLED:
                painter.drawLine(4, 8, 12, 8)
            case _:
                assert_never(self.owner.call.state)


class ToolCall(QtWidgets.QWidget):
    __slots__ = ('call', 'copy', 'copy_action', 'ink', 'presented', 'status', 'title')

    def __init__(self, parent: QtWidgets.QWidget, call: Call, copy: Callable[[str], None] = copy_text) -> None:
        super().__init__(parent)
        self.copy_action, self.call, self.ink = copy, call, Ink()
        self.presented: tuple[Call, int] | None = None
        self.setObjectName('toolCall-' + call.identity)
        self.status = StatusIcon(self)
        self.title = QtWidgets.QLabel(self)
        self.title.setTextFormat(Qt.TextFormat.PlainText)
        self.title.setFont(font(9))
        self.title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.copy = QtWidgets.QPushButton('Copy', self)
        self.copy.setFont(font(8))
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
        copy_width = 44 if call.copy_text else 0
        text_width = max(1, width - 24 - copy_width)
        preview = call.result if call.state is State.FAILED else call.argument or call.result
        label = call.label + (' · ' + shortened(' '.join(preview.split()), 240) if preview else '')
        self.title.setText(self.title.fontMetrics().elidedText(label, Qt.TextElideMode.ElideRight, text_width))
        self.status.setGeometry(0, 6, 16, 16)
        self.title.setGeometry(24, 0, text_width, ROW_HEIGHT)
        self.copy.setGeometry(max(24, width - 40), 2, 40, 24)
        self.setAccessibleName('Tool call: ' + call.name)
        self.setAccessibleDescription(call.state.value)
        self.copy.setAccessibleName(('Copy arguments for ' if call.argument else 'Copy result for ') + call.name)
        detail = '\n'.join(part for part in (call.name + ' · ' + call.state.value,
                                           shortened(call.argument, 800), shortened(call.result, 800)) if part)
        self.setToolTip('<pre>' + escape(detail) + '</pre>')
        self.recolor(self.ink)
        self.presented = (call, width)
        return ROW_HEIGHT

    def pulse(self, angle: float) -> None:
        if self.call.state is State.RUNNING:
            self.status.angle = angle
            self.status.update()

    def recolor(self, ink: Ink) -> None:
        self.ink = ink
        self.setStyleSheet(f'QWidget#{self.objectName()} {{ background: transparent; border: none; }}')
        self.title.setStyleSheet(f'background: transparent; border: none; padding: 0; margin: 0; color: {ink.foreground};')
        self.copy.setStyleSheet(f'background: transparent; border: none; padding: 0; margin: 0; color: {ink.secondary};')
        self.status.update()

    def toPlainText(self) -> str:
        return '\n'.join(part for part in (self.call.label, self.call.state.value, self.call.name,
                                          self.call.argument, self.call.result) if part)
