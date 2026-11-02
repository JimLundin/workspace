"""A request expands inside the toolbar's existing capsule, without navigation."""

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import override

lazy from PySide6 import QtCore, QtGui, QtWidgets

from assistant.canvas_activity import CanvasRequest
from automation.task import Approval
from desktop_ui import notification_text
from desktop_ui.agent_progress import Phase
from desktop_ui.agent_session import AgentRequest, pending
from desktop_ui.card_actions import CardAction, parse
from desktop_ui.components.appearance import GREEN, RED, Look, Shade
from desktop_ui.components.bubble import Controls, action_face, action_style
from desktop_ui.components.canvas_jump import CanvasJumpButton
from desktop_ui.components.text import Document, TextInk, TextView, color
from desktop_ui.notifications import Entry, hint, results
from desktop_ui.qt_runtime import prepare
from desktop_ui.rich_text import Span

prepare()

WIDTH = 360
PAD = 16


@dataclass(frozen=True, slots=True)
class RequestActions:
    """The exact decision, reply selection and review-presentation effect ports."""

    invoke: Callable[[CardAction], None]
    select: Callable[[CanvasRequest | None], None]
    presented: Callable[[str], None]


def controls(look: Look) -> Controls:
    ink = look.lettering
    return Controls(ink.ink, ink.hover, ink.hover, ink.press, Shade(ink.ink.color, 0), ink.ink, ink.press, ink.ink)


class RequestPanel(QtWidgets.QWidget):
    """Qt owns these child widgets, their scroll position and native lifetimes.

    The request itself and its action membership remain immutable observations.
    The capsule clips this panel while its existing spring expands the window.
    """

    def __init__(self, parent: QtWidgets.QWidget, actions: RequestActions) -> None:
        super().__init__(parent)
        self.ports: RequestActions = actions
        self.phase: Phase | None = None
        self.measurement = Document()
        self.body = TextView(self, self.scroll_text, self.copy_menu)
        self.body.setOpenExternalLinks(False)
        self.body.setOpenLinks(False)
        self.body.anchorClicked.connect(self.link)
        self.body.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.prompt = QtWidgets.QLabel(self)
        self.prompt.setFont(action_face(primary=False))
        self.options: tuple[tuple[Span, QtWidgets.QPushButton], ...] = ()
        self.canvas = CanvasJumpButton(
            self,
            Controls(
                Shade("#ffffff"),
                Shade("#000000", 0),
                Shade("#ffffff", 0.1),
                Shade("#ffffff", 0.2),
                Shade("#000000", 0),
                Shade("#ffffff"),
                Shade("#000000"),
                Shade("#ffffff"),
            ),
        )
        self.canvas.setText("")
        self.canvas.setFixedSize(28, 28)
        self.canvas.clicked.connect(self.open_canvas)
        self.canvas_span: Span | None = None
        self.body_height = 0

    def measure(self, phase: Phase) -> int:
        spans = notification_text.bubble_text(notification_text.spans(phase.turn)).body
        height = self.measurement.load(spans, WIDTH - 2 * PAD)
        return min(264, max(40, math.ceil(height))) + 52

    def present(self, phase: Phase, look: Look) -> None:
        self.phase = phase
        style = controls(look)
        ink = look.lettering
        self.body.recolor(TextInk(ink.ink, ink.quiet, ink.ink, Shade(RED), Shade(GREEN), ink.hover, ink.press, ink.ink))
        presentation = notification_text.bubble_text(notification_text.spans(phase.turn))
        self.body.update_spans(presentation.body, WIDTH - 2 * PAD)
        self.body_height = self.measure(phase) - 52
        self.body.setGeometry(PAD, 4, WIDTH - 2 * PAD, self.body_height)
        options = notification_text.options(phase.turn)
        if options != tuple(span for span, _ in self.options):
            for _, button in self.options:
                button.hide()
                button.deleteLater()
            self.options = tuple((span, self.button(span)) for span in options)
        left = PAD
        for span, button in self.options:
            button.setStyleSheet(action_style(style, primary=span.text == "Approve"))
            button.setGeometry(left, self.body_height + 16, 100, 28)
            button.show()
            left += 108
        self.prompt.setText(hint(phase.turn) if not options else "")
        self.prompt.setStyleSheet("color: " + color(ink.quiet).name() + "; background: transparent;")
        self.prompt.setGeometry(PAD, self.body_height + 16, WIDTH - 2 * PAD - 40, 28)
        self.canvas_span = presentation.canvas_actions[0] if presentation.canvas_actions else None
        self.canvas.recolor(style)
        self.canvas.move(WIDTH - PAD - 28, self.body_height + 16)
        self.canvas.setVisible(self.canvas_span is not None)

    def button(self, span: Span) -> QtWidgets.QPushButton:
        button = QtWidgets.QPushButton(span.text, self)
        button.setFont(action_face(primary=span.text == "Approve"))
        button.setAccessibleName(span.text)
        button.clicked.connect(lambda: self.follow(span))
        return button

    def follow(self, span: Span) -> None:
        action = parse(span.link)
        if action is not None:
            self.ports.invoke(action)

    def open_canvas(self) -> None:
        if self.canvas_span is not None:
            self.follow(self.canvas_span)

    def link(self, url: QtCore.QUrl) -> None:
        action = parse(url.toString())
        if action is not None:
            self.ports.invoke(action)

    def scroll_text(self, delta: int) -> None:
        bar = self.body.verticalScrollBar()
        bar.setValue(bar.value() - delta)

    def copy_menu(self, point: QtCore.QPoint) -> None:
        menu = self.body.createStandardContextMenu()
        menu.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose)
        menu.popup(point)

    @override
    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        super().paintEvent(event)
        if self.phase is not None and self.isEnabled():
            for entry in results(self.phase.turn):
                match entry:
                    case Entry(message=AgentRequest(request=Approval()) as request) if pending(request):
                        self.ports.presented(request.id)
                    case _:
                        pass
