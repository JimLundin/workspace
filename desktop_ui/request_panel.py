"""What the island expands into in place: a request, or the bell's list.

The question reads as plain text: its line in bold, then its detail. A canvas
link in the detail becomes the canvas button instead of prose. The list puts
questions and recent notices together as one-line rows.
"""

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import assert_never

lazy from PySide6 import QtCore, QtGui, QtWidgets

from contracts.agent_session import AgentRequest, pending
from contracts.canvas_activity import CanvasRequest
from contracts.card_actions import OpenCanvas
from desktop_ui.agent_progress import Entry, Phase, hint
from desktop_ui.bar_control import KeyboardFocus
from desktop_ui.components.appearance import Look, Shade
from desktop_ui.components.bubble import Controls
from desktop_ui.components.canvas_jump import CanvasJumpButton
from desktop_ui.components.text import color, face
from desktop_ui.island_moment import Asked, Notice, Row
from desktop_ui.plain_text import plain
from desktop_ui.qt_runtime import prepare
from desktop_ui.vector_icons import icon

prepare()

WIDTH = 360
PAD = 16
DETAIL = 220  # The detail scrolls beyond this height.
ROW = 48


@dataclass(frozen=True, slots=True)
class RequestActions:
    """The canvas-link and reply-selection effect ports."""

    invoke: Callable[[OpenCanvas], None]
    select: Callable[[CanvasRequest | None], None]


@dataclass(frozen=True, slots=True)
class Request:
    question: str
    detail: str
    canvas: str | None
    hint: str


def request(phase: Phase) -> Request:
    """The phase's pending question, else its latest one, as plain text."""
    asked = tuple(entry.message for entry in phase.turn.entries if isinstance(entry, Entry) and isinstance(entry.message, AgentRequest))
    shown = next((message for message in asked if pending(message)), asked[-1] if asked else None)
    if shown is None:
        return Request("", "", None, "")
    detail = plain(shown.detail)
    return Request(plain(shown.text).text, detail.text if detail.text != shown.text else "", detail.canvas, hint(phase.turn))


def controls(look: Look) -> Controls:
    ink = look.lettering
    return Controls(ink.ink, ink.hover, ink.hover, ink.press, Shade(ink.ink.color, 0), ink.ink, ink.press, ink.ink)


def text_height(font: QtGui.QFont, text: str) -> int:
    if not text:
        return 0
    bounds = QtGui.QFontMetrics(font).boundingRect(QtCore.QRect(0, 0, WIDTH - 2 * PAD, 100_000), QtCore.Qt.TextFlag.TextWordWrap, text)
    return math.ceil(bounds.height())


class RequestPanel(QtWidgets.QWidget):
    """Qt owns these child widgets, their scroll position and native lifetimes.

    The request itself remains an immutable observation.
    The capsule clips this panel while its existing spring expands the window.
    """

    def __init__(self, parent: QtWidgets.QWidget, actions: RequestActions) -> None:
        super().__init__(parent)
        self.ports: RequestActions = actions
        self.phase: Phase | None = None
        self.target: str | None = None
        self.question = QtWidgets.QLabel(self)
        self.question.setFont(face(13, 600))
        self.question.setWordWrap(True)
        self.question.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        self.body = QtWidgets.QPlainTextEdit(self)
        self.body.setReadOnly(True)
        self.body.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self.body.setFont(face(13))
        self.body.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.body.document().setDocumentMargin(0)
        self.prompt = QtWidgets.QLabel(self)
        self.prompt.setFont(face(12))
        self.canvas = CanvasJumpButton(self, controls_on_glass())
        self.canvas.clicked.connect(self.open_canvas)

    def measure(self, phase: Phase) -> int:
        shown = request(phase)
        detail = min(DETAIL, text_height(self.body.font(), shown.detail))
        return 4 + text_height(self.question.font(), shown.question) + (8 + detail if detail else 0) + 12 + 28 + 12

    def present(self, phase: Phase, look: Look) -> None:
        self.phase = phase
        shown = request(phase)
        ink, quiet = (
            color(look.lettering.ink).name(QtGui.QColor.NameFormat.HexArgb),
            color(look.lettering.quiet).name(QtGui.QColor.NameFormat.HexArgb),
        )
        self.question.setStyleSheet(f"color: {ink}; background: transparent;")
        self.body.setStyleSheet(f"QPlainTextEdit {{ color: {ink}; background: transparent; }}")
        self.prompt.setStyleSheet(f"color: {quiet}; background: transparent;")
        question = text_height(self.question.font(), shown.question)
        self.question.setText(shown.question)
        self.question.setGeometry(PAD, 4, WIDTH - 2 * PAD, question)
        detail = min(DETAIL, text_height(self.body.font(), shown.detail))
        if self.body.toPlainText() != shown.detail:
            self.body.setPlainText(shown.detail)
        self.body.setGeometry(PAD, 4 + question + 8, WIDTH - 2 * PAD, detail)
        self.body.setVisible(bool(detail))
        bottom = 4 + question + (8 + detail if detail else 0) + 12
        self.prompt.setText(shown.hint)
        self.prompt.setGeometry(PAD, bottom, WIDTH - 2 * PAD - 40, 28)
        self.target = shown.canvas
        self.canvas.recolor(controls(look))
        self.canvas.move(WIDTH - PAD - 28, bottom)
        self.canvas.setVisible(shown.canvas is not None)

    def open_canvas(self) -> None:
        if self.target is not None:
            self.ports.invoke(OpenCanvas(self.target))


def controls_on_glass() -> Controls:
    white, clear = Shade("#ffffff"), Shade("#000000", 0)
    return Controls(white, clear, Shade("#ffffff", 0.1), Shade("#ffffff", 0.2), clear, white, Shade("#000000"), white)


@dataclass(frozen=True, slots=True)
class Line:
    symbol: str
    title: str
    text: str


def line(row: Row) -> Line:
    match row:
        case Asked(phase=phase):
            shown = request(phase)
            return Line("bell", shown.question or "Your input is needed", " ".join(shown.detail.split()))
        case Notice(title=title, text=text):
            return Line("agent", title, " ".join(text.split()))
        case _:
            assert_never(row)


def list_height(rows: tuple[Row, ...]) -> int:
    return 4 + ROW * len(rows) + 8


class InboxRow(KeyboardFocus):
    """One question or notice; pressing it opens the question here, or the notice's canvas item."""

    def __init__(self, panel: InboxPanel, row: Row) -> None:
        super().__init__(panel)
        self.panel = panel
        self.row = row
        self.look: Look | None = None
        shown = line(row)
        self.setAccessibleName(": ".join(part for part in (shown.title, shown.text) if part))
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        self.clicked.connect(lambda: panel.choose(self.row))

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        if self.look is None:
            return
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        lettering = self.look.lettering
        self.paint_feedback(painter, lettering, selected=False)
        shown = line(self.row)
        painter.setOpacity(lettering.ink.opacity)
        icon(shown.symbol, lettering.ink.color).paint(painter, QtCore.QRect(12, (self.height() - 16) // 2, 16, 16))
        painter.setOpacity(1)
        width = self.width() - 40 - 12
        title, text = face(13, 600), face(12)
        painter.setFont(title)
        painter.setPen(color(lettering.ink))
        top = QtCore.QRectF(40, 6, width, 18 if shown.text else self.height() - 12)
        align = QtCore.Qt.AlignmentFlag.AlignLeft | (QtCore.Qt.AlignmentFlag.AlignBottom if shown.text else QtCore.Qt.AlignmentFlag.AlignVCenter)
        painter.drawText(top, align, QtGui.QFontMetricsF(title).elidedText(shown.title, QtCore.Qt.TextElideMode.ElideRight, width))
        if shown.text:
            painter.setFont(text)
            painter.setPen(color(lettering.quiet))
            elided = QtGui.QFontMetricsF(text).elidedText(shown.text, QtCore.Qt.TextElideMode.ElideRight, width)
            painter.drawText(QtCore.QRectF(40, 25, width, 17), QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignTop, elided)


class InboxPanel(QtWidgets.QWidget):
    """The bell's rows, rebuilt only when the list changes; the capsule clips it while it morphs open."""

    def __init__(self, parent: QtWidgets.QWidget, choose: Callable[[Row], None]) -> None:
        super().__init__(parent)
        self.choose = choose
        self.rows: tuple[InboxRow, ...] = ()

    def present(self, rows: tuple[Row, ...], look: Look) -> None:
        if tuple(each.row for each in self.rows) != rows:
            for each in self.rows:
                each.hide()
                each.deleteLater()
            self.rows = tuple(InboxRow(self, row) for row in rows)
        for index, each in enumerate(self.rows):
            each.look = look
            each.setGeometry(6, 4 + index * ROW, WIDTH - 12, ROW - 4)
            each.show()
            each.update()
