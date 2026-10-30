"""Native step composition keeps identified tool widgets separate from replies.

Qt owns the scroll area, child lifetimes and text documents. Tuple snapshots
retain widgets across status updates and disclosure; retired identities are
deleted by this owner. Measurement uses the same text adapters as the children.
"""

import math
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass

lazy import shiboken6
lazy from PySide6 import QtGui, QtWidgets
lazy from PySide6.QtCore import QPoint, Qt
lazy from PySide6.QtGui import QWheelEvent

from assistant import notification_text, tool_call_view, tool_text
from assistant.notifications import Content
from assistant.qt_runtime import prepare
from assistant.ui_components.appearance import Ink
from assistant.ui_components.text import Document, TextView

prepare()

GAP = 8


@dataclass(frozen=True, slots=True)
class Callbacks:
    scroll: Callable[[int], None]
    history: Callable[[], None]
    copy: Callable[[str], None] = tool_call_view.copy_text


class Measure:
    __slots__ = ("history",)

    def __init__(self) -> None:
        self.history = Document()

    def height(self, block: notification_text.Step, width: float) -> float:
        match block:
            case tool_text.Call():
                return tool_call_view.ROW_HEIGHT
            case notification_text.HistoryStep(spans=values):
                return self.history.load(values, width)

    def total(self, blocks: Iterable[notification_text.Step], width: float) -> float:
        return sum(self.height(block, width) + (GAP if index else 0) for index, block in enumerate(blocks))

    def intrinsic_width(self, blocks: tuple[notification_text.Step, ...], maximum: float) -> float:
        return maximum if blocks else 0

    def close(self) -> None:
        self.history.close()


class HistoryView(QtWidgets.QWidget):
    __slots__ = ("callbacks", "identity", "text")

    def __init__(self, parent: QtWidgets.QWidget, block: notification_text.HistoryStep, callbacks: Callbacks) -> None:
        super().__init__(parent)
        self.callbacks, self.identity = callbacks, block.identity
        self.text = TextView(self, callbacks.scroll, self.menu)
        self.setAccessibleName("Earlier conversation reply")

    def menu(self, point: QPoint) -> None:
        self.text.copy_menu(point, self.callbacks.history)

    def present(self, block: notification_text.HistoryStep, width: int) -> int:
        self.text.update_spans(block.spans, width)
        height = math.ceil(self.text.content.height)
        self.resize(width, height)
        self.text.setGeometry(0, 0, width, height)
        self.text.fit_width()
        return height

    def recolor(self, ink: Ink) -> None:
        self.text.recolor(ink)

    def toPlainText(self) -> str:
        return self.text.toPlainText()


type Element = tool_call_view.ToolCall | HistoryView


class StepsView(QtWidgets.QScrollArea):
    __slots__ = ("callbacks", "canvas", "elements", "ink", "visible_blocks")

    def __init__(self, parent: QtWidgets.QWidget, scroll: Callable[[int], None], history: Callable[[], None]) -> None:
        super().__init__(parent)
        self.callbacks = Callbacks(scroll, history)
        self.ink = Ink()
        self.elements: tuple[Element, ...] = ()
        self.visible_blocks: tuple[notification_text.Step, ...] = ()
        self.setObjectName("agentSteps")
        self.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self.setStyleSheet("QScrollArea#agentSteps { background: transparent; border: none; }")
        self.viewport().setAutoFillBackground(False)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setWidgetResizable(False)
        self.canvas = QtWidgets.QWidget(self)
        self.canvas.setAutoFillBackground(False)
        self.setWidget(self.canvas)
        self.setAccessibleName("Agent tool calls and steps")

    @property
    def offset(self) -> int:
        return self.verticalScrollBar().value()

    @property
    def calls(self) -> tuple[tool_call_view.ToolCall, ...]:
        return tuple(self.tool_elements())

    def tool_elements(self) -> Iterator[tool_call_view.ToolCall]:
        for element in self.elements:
            match element:
                case tool_call_view.ToolCall():
                    yield element
                case HistoryView():
                    pass

    def clear(self) -> None:
        """Release logical steps while retaining the native scroll surface."""
        for element in self.elements:
            shiboken6.delete(element)
        self.elements = ()
        self.visible_blocks = ()
        self.verticalScrollBar().setValue(0)
        self.hide()

    def obtain(self, block: notification_text.Step) -> Element:
        prior = next((element for element in self.elements if element.identity == block.identity), None)
        match block, prior:
            case tool_text.Call(), tool_call_view.ToolCall():
                return prior
            case notification_text.HistoryStep(), HistoryView():
                return prior
            case tool_text.Call(), _:
                return tool_call_view.ToolCall(self.canvas, block, self.callbacks.copy)
            case notification_text.HistoryStep(), _:
                return HistoryView(self.canvas, block, self.callbacks)

    def present(self, content: Content, width: float, *, expanded: bool) -> None:
        blocks = notification_text.step_blocks(content, expanded=True)
        updated = tuple(self.obtain(block) for block in blocks)
        for element in self.elements:
            if element not in updated:
                shiboken6.delete(element)
        self.elements = updated
        for block, element in zip(blocks, updated, strict=True):
            match block, element:
                case tool_text.Call(), tool_call_view.ToolCall():
                    element.present(block, max(1, round(width)))
                case notification_text.HistoryStep(), HistoryView():
                    element.present(block, max(1, round(width)))
                case _:
                    raise RuntimeError("A step identity changed its presentation variant.")
        self.visible_blocks = notification_text.step_blocks(content, expanded=expanded)
        self.place(max(1, round(width)))

    def place(self, width: int) -> None:
        offset = self.offset
        visible = tuple(block.identity for block in self.visible_blocks)
        for element in self.elements:
            element.setVisible(element.identity in visible)
        top = 0
        for index, block in enumerate(self.visible_blocks):
            element = next(element for element in self.elements if element.identity == block.identity)
            if index:
                top += GAP
            match block, element:
                case tool_text.Call(), tool_call_view.ToolCall():
                    height = element.present(block, width)
                case notification_text.HistoryStep(), HistoryView():
                    height = element.present(block, width)
                case _:
                    raise RuntimeError("A step identity changed its presentation variant.")
            element.recolor(self.ink)
            element.move(0, top)
            element.show()
            top += height
        self.canvas.resize(width, top)
        self.verticalScrollBar().setValue(offset)

    def fit_width(self) -> None:
        self.place(max(1, self.viewport().width()))

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        # Qt resolves the scroll viewport after the card sets its bounds. Reflow
        # retained rows at that boundary instead of keeping the initial 100px width.
        super().resizeEvent(event)
        self.fit_width()

    def recolor(self, ink: Ink) -> None:
        self.ink = ink
        for element in self.elements:
            element.recolor(ink)

    def pulse(self, angle: float) -> None:
        for element in self.tool_elements():
            if not element.isHidden():
                element.pulse(angle)

    def toPlainText(self) -> str:
        visible = tuple(block.identity for block in self.visible_blocks)
        return "\n\n".join(element.toPlainText() for element in self.elements if element.identity in visible)

    def wheelEvent(self, event: QWheelEvent) -> None:
        self.callbacks.scroll(event.angleDelta().y())
        event.accept()
