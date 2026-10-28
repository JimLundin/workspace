"""A native tool-call element owns its header, payload views and copy action.

Qt owns mutable widgets and documents. Only immutable call observations enter;
the element's lifetime follows the invocation identity, never its status text.
"""

import math
from collections.abc import Callable
from dataclasses import dataclass

from .qt import QPoint, Qt, QtWidgets
from .qt_text import Document, TextView, font
from .rich_text import Span
from .toast_style import Ink
from .tool_text import Call, State

INSET = 8
HEADER = 24
NAME = 18
GAP = 4
RESULT_LABEL = 18


@dataclass(frozen=True, slots=True)
class Callbacks:
    scroll: Callable[[int], None]
    history: Callable[[], None]


@dataclass(frozen=True, slots=True)
class Size:
    argument: int
    result: int

    @property
    def height(self) -> int:
        return INSET * 2 + HEADER + NAME + (GAP + self.argument if self.argument else 0) + (
            GAP + RESULT_LABEL + self.result if self.result else 0)


def literal(text: str) -> tuple[Span, ...]:
    return (Span(text, ('code', 'codeblock', 'step_detail')),) if text else ()


class Measure:
    __slots__ = ('document',)

    def __init__(self) -> None:
        self.document = Document()

    def size(self, call: Call, width: float) -> Size:
        text_width = max(1, width - INSET * 2)
        argument = math.ceil(self.document.load(literal(call.argument), text_width)) if call.argument else 0
        result = math.ceil(self.document.load(literal(call.result), text_width)) if call.result else 0
        return Size(argument, result)

    def close(self) -> None:
        self.document.close()


class ToolCall(QtWidgets.QWidget):
    __slots__ = ('argument', 'call', 'callbacks', 'copy', 'ink', 'name', 'presented', 'result', 'result_label', 'status', 'title')

    def __init__(self, parent: QtWidgets.QWidget, call: Call, callbacks: Callbacks) -> None:
        super().__init__(parent)
        self.callbacks, self.call, self.ink = callbacks, call, Ink()
        self.presented: tuple[Call, int] | None = None
        self.setObjectName('toolCall-' + call.identity)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.title = QtWidgets.QLabel(self)
        self.status = QtWidgets.QLabel(self)
        self.name = QtWidgets.QLabel(self)
        self.result_label = QtWidgets.QLabel('Result', self)
        for label in (self.title, self.status, self.name, self.result_label):
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setFont(font(9.5, bold=label is self.title))
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.name.setFont(font(9, family='Consolas'))
        self.copy = QtWidgets.QPushButton('Copy', self)
        self.copy.setFont(font(8))
        self.copy.clicked.connect(self.copy_payload)
        self.argument = TextView(self, callbacks.scroll, self.argument_menu)
        self.result = TextView(self, callbacks.scroll, self.result_menu)
        self.argument.setAccessibleName('Tool arguments')
        self.result.setAccessibleName('Tool result')

    @property
    def identity(self) -> str:
        return self.call.identity

    def copy_payload(self) -> None:
        QtWidgets.QApplication.clipboard().setText(self.call.copy_text)

    def argument_menu(self, point: QPoint) -> None:
        self.argument.copy_menu(point, self.callbacks.history)

    def result_menu(self, point: QPoint) -> None:
        self.result.copy_menu(point, self.callbacks.history)

    def present(self, call: Call, width: int) -> int:
        if self.presented == (call, width):
            return self.height()
        self.call = call
        self.title.setText(call.symbol + '  ' + call.label)
        self.status.setText(call.state.value)
        self.name.setText(call.name)
        self.setAccessibleName('Tool call: ' + call.name)
        self.setAccessibleDescription(call.state.value)
        self.copy.setAccessibleName('Copy arguments for ' + call.name if call.argument else 'Copy result for ' + call.name)
        self.copy.setVisible(bool(call.copy_text))
        text_width = max(1, width - INSET * 2)
        self.argument.update_spans(literal(call.argument), text_width)
        self.result.update_spans(literal(call.result), text_width)
        size = Size(math.ceil(self.argument.content.height), math.ceil(self.result.content.height))
        self.resize(width, size.height)
        self.title.setGeometry(INSET, INSET, max(1, width - 160), HEADER)
        self.status.setGeometry(max(INSET, width - 142), INSET, 82, HEADER)
        self.copy.setGeometry(max(INSET, width - 54), INSET, 46, HEADER)
        self.name.setGeometry(INSET, INSET + HEADER, text_width, NAME)
        top = INSET + HEADER + NAME
        self.argument.setVisible(bool(size.argument))
        if size.argument:
            top += GAP
            self.argument.setGeometry(INSET, top, text_width, size.argument)
            self.argument.fit_width()
            top += size.argument
        self.result_label.setVisible(bool(size.result))
        self.result.setVisible(bool(size.result))
        if size.result:
            top += GAP
            self.result_label.setGeometry(INSET, top, text_width, RESULT_LABEL)
            self.result.setGeometry(INSET, top + RESULT_LABEL, text_width, size.result)
            self.result.fit_width()
        self.recolor(self.ink)
        self.presented = (call, width)
        return size.height

    def recolor(self, ink: Ink) -> None:
        self.ink = ink
        self.setStyleSheet(f'QWidget#{self.objectName()} {{ background: rgba(118,106,154,18); '
                          f'border: 1px solid {ink.secondary}; border-radius: 9px; }}')
        for label in (self.title, self.name, self.result_label):
            label.setStyleSheet(f'background: transparent; border: none; color: {ink.foreground};')
        status_color = ink.error if self.call.state is State.FAILED else ink.foreground
        self.status.setStyleSheet(f'background: rgba(118,106,154,24); border: none; border-radius: 6px; color: {status_color};')
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.copy.setStyleSheet(f'background: transparent; border: none; color: {ink.secondary};')
        self.argument.recolor(ink)
        self.result.recolor(ink)

    def toPlainText(self) -> str:  # noqa: N802 -- matches the native conversation text interface
        return '\n'.join(part for part in (self.title.text(), self.status.text(), self.call.name,
                                          self.call.argument, self.call.result) if part)
