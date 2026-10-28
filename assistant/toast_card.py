"""One rounded conversation surface with independent steps and attached result."""

import math
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum, auto
from html import escape
from typing import TYPE_CHECKING

lazy import shiboken6
lazy from PySide6 import QtCore, QtWidgets
lazy from PySide6.QtCore import QPoint, QRectF, Qt
lazy from PySide6.QtGui import (
    QColor,
    QContextMenuEvent,
    QFontMetricsF,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
    QTextCharFormat,
    QTextCursor,
)
lazy from PySide6.QtWidgets import QAbstractButton, QLabel, QTextEdit, QWidget

import assistant.feed_icons
from assistant import notification_reading, notification_text, step_view
from assistant.agent_session import StreamState
from assistant.agent_window import log_view
from assistant.feed_items import WorkItem
from assistant.feed_origin import App, Origin
from assistant.feed_title import TITLE_SIZE, FeedTitle, heading_width
from assistant.feed_triage import Assessment, proposal_revision, solutions_for
from assistant.notifications import (
    REVEAL_SECONDS,
    Busy,
    Content,
    Entry,
    Frame,
    Motion,
    Recording,
    Settled,
    Toast,
    Tone,
    Turn,
    Working,
    can_stop,
    caption,
    display_order,
    heading,
    hint,
    origin_item,
    spinning,
    tone,
)
from assistant.qt_runtime import prepare
from assistant.qt_text import INSET, TEXT_PADDING, Document, TextView, font, units
from assistant.rich_text import Span
from assistant.toast_style import Ink, Palette, palette
from winapi import appearance, windows
from winapi.composition import DesktopComposition, Glass
from winapi.shapes import Rect

prepare()

if TYPE_CHECKING:
    from assistant.agent_toasts import AgentToasts


@dataclass(frozen=True, slots=True)
class Prepared:
    width: int
    spans: tuple[Span, ...]
    body_height: int
    header_height: int
    label_width: int
    hint: str
    hint_height: int
    caption: str
    details: tuple[notification_text.Step, ...]
    details_height: int
    details_limit: int
    padding: int
    text_width: int

    @property
    def preferred(self) -> int:
        return self.header_height + min(self.details_height, self.details_limit) + self.body_height + self.hint_height + self.padding


@dataclass(frozen=True, slots=True)
class Layout:
    details_height: int
    body_height: int
    hint: str
    hint_height: int
    height: int


@dataclass(frozen=True, slots=True)
class Reveal:
    start: int
    end: int
    started: float


def choice_geometry(labels: tuple[str, ...], width: float) -> tuple[tuple[int, int, int], ...]:
    metrics = QFontMetricsF(font(8.5))
    x = y = 0
    result: list[tuple[int, int, int]] = []
    for label in labels:
        wide = min(round(width), math.ceil(metrics.horizontalAdvance(label) + 20))
        if x and x + wide > width:
            x, y = 0, y + 30
        result.append((x, y, wide))
        x += wide + 6
    return tuple(result)


class Measure:
    __slots__ = ("body", "details", "scale")

    def __init__(self) -> None:
        self.body, self.details = Document(), step_view.Measure()
        self.scale = 1.0

    def text_height(self, text: str, size: float, width: float, *, bold: bool = False) -> float:
        metrics = QFontMetricsF(font(size, bold=bold))
        return metrics.boundingRect(QRectF(0, 0, max(1, width), 10000), Qt.TextFlag.TextWordWrap.value, text).height() if text else 0

    def prepare(self, content: Content, maximum: int, *, expanded: bool = False) -> Prepared:
        scale = self.scale
        user = tone(content) is Tone.USER
        compact = isinstance(content, WorkItem) or (isinstance(content, Turn) and isinstance(content.state, Settled))
        source = origin_item(content)
        curated = source is not None and isinstance(source.item, Assessment)
        inset = 8
        maximum_width = min(maximum / scale, 280 if user else maximum / scale)
        spans = notification_text.spans(content, expanded=expanded)
        if curated and isinstance(content, WorkItem):
            spans = spans[1:] if expanded else ()
        details = notification_text.step_blocks(content, expanded=expanded)
        meta, footer = '' if compact else caption(content), "You" if user else hint(content)
        if isinstance(content, (Entry, Turn)):
            # Agent questions use the bubble's voice tooltip, with no input footer.
            footer = ''
        badge_width = 28 + 18 * (min(3, len(source.origins)) - 1) if source is not None and source.origins else 28
        controls = ((26 if not user else 0)
                    + (26 if notification_text.expandable(content) and not curated else 0) + (32 if can_stop(content) else 0))
        label = notification_text.title_text(content) if isinstance(content, Turn) or curated else '' if compact else heading(content)
        body_padding = INSET * 2 + 8
        # The feed has one column width. Only the person's speech uses a smaller
        # bubble; standalone replies must match conversation and proposal cards.
        width = maximum_width
        if user:
            body_width = self.body.intrinsic_width(spans, max(1, maximum_width - body_padding))
            width = min(maximum_width, max(100, badge_width + INSET * 2, body_width + body_padding))
        labels = (tuple(option.label for option in solutions_for(content.item))
                  if isinstance(content, WorkItem) and isinstance(content.item, Assessment)
                  else tuple(span.text for span in notification_text.options(content)))
        text_width = max(1, round(math.ceil(width * scale) / scale) - body_padding)
        body_height = self.body.load(spans, text_width) + TEXT_PADDING * 2 if spans else 0
        details_height = self.details.total(details, text_width) + TEXT_PADDING * 2 if details else 0
        label_width: float = max(1, round(math.ceil(width * scale) / scale) - controls - badge_width - INSET * 2)
        if curated or isinstance(content, Turn):
            label_width = heading_width(round(math.ceil(width * scale) / scale), badge_width,
                                        stopping=can_stop(content), disclosing=notification_text.expandable(content) and not curated)
            title_height = (self.text_height(label, TITLE_SIZE, label_width, bold=True) if expanded
                            else QFontMetricsF(font(TITLE_SIZE, bold=True)).height())
            header: float = 16 + max(24, math.ceil(title_height)) + 6
        else:
            header = 20 if user else 36 if compact else inset + 14 + max(28, self.text_height(label, 9.5, label_width, bold=True)
                                                                      + self.text_height(meta, 8.5, label_width)) + 8
        footer_height = self.text_height(footer, 8.5, text_width) + 8 if footer and not user else 0
        if labels:
            geometry = choice_geometry(labels, text_width)
            footer_height = geometry[-1][1] + 30
            footer = ''
        return Prepared(math.ceil(width * scale), spans, math.ceil(body_height * scale), math.ceil(header * scale),
                        math.floor(label_width * scale), footer, math.ceil(footer_height * scale), meta, details,
                        math.ceil(details_height * scale), round(200 * scale), round(8 * scale), math.floor(text_width * scale))

    def fit_body(self, document: Document, spans: tuple[Span, ...], width: int, available: int) -> int:
        if not spans:
            return 0
        document.load(spans, max(1, width / self.scale))
        fitted = document.fit(available / self.scale - TEXT_PADDING * 2)
        return math.ceil((fitted + TEXT_PADDING * 2) * self.scale) if fitted else 0

    def layout(self, prepared: Prepared, width: int, maximum: int) -> Layout:
        available = max(0, maximum - prepared.header_height - prepared.hint_height - prepared.padding)
        budget = min(prepared.details_limit, max(0, available - min(prepared.body_height, available // 2)))
        text_width = max(1, prepared.text_width + width - prepared.width)
        details = min(prepared.details_height, budget)
        available -= details
        body = (self.fit_body(self.body, prepared.spans, text_width, available)
                if prepared.body_height > available else prepared.body_height)
        return Layout(details, body, prepared.hint, prepared.hint_height,
                      prepared.header_height + details + body + prepared.hint_height + prepared.padding)

    def close(self) -> None:
        self.body.close()
        self.details.close()


class Icon(Enum):
    STOP = auto()
    DISCLOSURE = auto()
    DISMISS = auto()


class IconButton(QAbstractButton):
    __slots__ = ("expanded", "ink", "key_click", "kind")

    def __init__(self, parent: QWidget, icon: Icon, key_click: Callable[[], None]) -> None:
        super().__init__(parent)
        self.kind = icon
        self.key_click = key_click
        self.expanded = False
        self.ink = "#f6f3ff"
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName("Dismiss item" if icon is Icon.DISMISS else "Stop agent" if icon is Icon.STOP else "Show steps")
        self.setToolTip(self.accessibleName())

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(self.ink), 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.setOpacity(.45 if not self.isEnabled() else .65 if self.isDown() else 1)
        cx, cy = self.width() / 2, self.height() / 2
        path = QPainterPath()
        match self.kind:
            case Icon.STOP:
                path.addRoundedRect(QRectF(cx - 4, cy - 4, 8, 8), 1, 1)
            case Icon.DISMISS:
                path.moveTo(cx - 4, cy - 4)
                path.lineTo(cx + 4, cy + 4)
                path.moveTo(cx + 4, cy - 4)
                path.lineTo(cx - 4, cy + 4)
            case Icon.DISCLOSURE:
                direction = -1 if self.expanded else 1
                path.moveTo(cx - 3.5, cy - direction * 1.5)
                path.lineTo(cx, cy + direction * 2)
                path.lineTo(cx + 3.5, cy - direction * 1.5)
        painter.drawPath(path)
        if self.hasFocus():
            painter.setPen(QPen(QColor(self.ink), 1, Qt.PenStyle.DotLine))
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(3, 3, -3, -3), 8, 8)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.setDown(True)
            event.accept()
        else:
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.setDown(False)
            if self.isEnabled() and not event.isAutoRepeat():
                self.key_click()
            event.accept()
        else:
            super().keyReleaseEvent(event)


class SourceBadge(QWidget):
    __slots__ = ('card',)

    def __init__(self, card: Card) -> None:
        super().__init__(card.window)
        self.card = card
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def source(self, content: Content) -> None:
        source = origin_item(content)
        sources = source.origins if source is not None and source.origins else (Origin(App.WORKSPACE, App.WORKSPACE.value),)
        names = ', '.join(origin.name for origin in sources)
        names += ' · You' if tone(content) is Tone.USER else ''
        self.setAccessibleName('From ' + names)
        self.setToolTip(escape(names))
        self.setGeometry(0, 0, 28 + 18 * (min(3, len(sources)) - 1), 28)
        self.show()
        self.raise_()
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        content = self.card.content
        source = origin_item(content)
        sources = source.origins if source is not None and source.origins else (Origin(App.WORKSPACE, App.WORKSPACE.value),)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        for index, origin in reversed(tuple(enumerate(sources[:3]))):
            x = index * 18
            painter.setPen(QPen(QColor(self.card.colors.edge), 1))
            painter.setBrush(QColor(self.card.colors.surface))
            painter.drawEllipse(QRectF(x + .5, .5, 27, 27))
            assistant.feed_icons.icon(origin.app).paint(painter, QtCore.QRect(x + 5, 5, 18, 18))
        if content is not None and spinning(content):
            painter.setPen(QPen(QColor(self.card.ink.foreground), 1.6))
            painter.drawArc(QRectF(1.5, 1.5, 25, 25), round(self.card.spin_angle * 16), 240 * 16)


class Bubble(QWidget):
    __slots__ = ("card",)

    def __init__(self, card: Card) -> None:
        super().__init__()
        self.card = card
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setWindowTitle("Workspace · Agent notification")
        self.setToolTip("Press the agent voice-to-text button (N) to reply.")

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        card = self.card
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        outline = QPainterPath()
        outline.addRoundedRect(QRectF(self.rect()).adjusted(8.5, 8.5, -.5, -.5), 26, 26)
        # A nonzero alpha also makes all empty space in the bubble a real mouse
        # target. Text and icon padding need no extra invisible native windows.
        painter.fillPath(outline, QColor(1, 1, 1, 1) if card.glass else QColor(card.colors.surface))
        edge = QColor(card.colors.edge)
        edge.setAlpha(85 if card.glass else 255)
        painter.setPen(QPen(edge, 1))
        painter.drawPath(outline)
        if card.content is None or card.prepared is None or tone(card.content) is Tone.USER:
            return
        if card.text.isVisible() and isinstance(card.content, Turn) and (not card.label.isHidden() or card.details.isVisible()):
            painter.setPen(QPen(edge, 1))
            top = card.text.y() - TEXT_PADDING
            painter.drawLine(INSET, top, self.width() - INSET, top)
        for text in (card.text, card.details):
            scroll = text.verticalScrollBar()
            if text.isVisible() and scroll.maximum() > 0:
                height = text.height()
                total = height + scroll.maximum()
                start = text.y() + height * scroll.value() / total
                end = start + max(8, height * height / total)
                painter.setPen(QPen(QColor(card.ink.secondary), 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                painter.drawLine(self.width() - 6, round(start), self.width() - 6, min(text.y() + height, round(end)))

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        prepared = self.card.prepared
        source = isinstance(self.card.content, WorkItem) and isinstance(self.card.content.item, Assessment)
        if (event.button() is Qt.MouseButton.LeftButton and prepared is not None
                and (source or event.position().y() < prepared[2].header_height / self.card.owner.scale)):
            self.card.toggle()
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:  # noqa: N802
        self.card.menu(event.globalPos())
        event.accept()


def _glass(composition: DesktopComposition) -> Glass:
    return composition.glass()


class Card:
    __slots__ = (
        "__weakref__",
        "badge",
        "bounds",
        "caption",
        "choice_revision",
        "choices",
        "chosen",
        "closed",
        "colors",
        "content",
        "create_glass",
        "detail_offset",
        "details",
        "disclosure",
        "dismiss",
        "expanded",
        "frame",
        "frost",
        "glass",
        "handle",
        "height",
        "hint",
        "hovered",
        "ink",
        "key",
        "label",
        "layer",
        "layout",
        "line_height",
        "look",
        "maximum",
        "motion",
        "move",
        "order",
        "owner",
        "page_origin",
        "prepared",
        "reader",
        "retiring",
        "reveals",
        "right",
        "spans",
        "speed",
        "spin_angle",
        "stop",
        "tail_pending",
        "text",
        "width",
        "window",
    )

    def __init__(self, owner: AgentToasts, toast: Toast, width: int, *,
                 move: Callable[[int, Rect], None] = windows.move,
                 glass: Callable[[DesktopComposition], Glass] | None = None) -> None:
        # Geometry and glass creation are the two native effects owned by a card;
        # injected adapters retain real widgets and the same scene lifetime.
        self.move, self.create_glass = move, _glass if glass is None else glass
        self.owner, self.key, self.order = owner, toast.key, display_order(toast, curated=owner.session.triage.enabled)
        self.content: Content | None = None
        self.prepared: tuple[Content, int, Prepared] | None = None
        self.layout: Layout | None = None
        self.bounds: Rect | None = None
        self.look: tuple[Tone, App | None, appearance.Preference, appearance.Frost] | None = None
        self.frost = appearance.Frost.SMOKED
        self.glass = self.closed = self.hovered = self.retiring = self.expanded = self.tail_pending = False
        self.motion: Motion | None = None
        self.reader: notification_reading.State = notification_reading.Waiting(0, owner.clock() + notification_reading.START_SECONDS)
        self.page_origin = self.speed = self.spin_angle = 0.0
        self.line_height = round(QFontMetricsF(font()).height() * owner.scale * 1.38)
        self.width, self.height, self.maximum, self.right = width, 1, 0, 0
        self.frame = Frame(0, width, 1, 0)
        self.spans: tuple[Span, ...] = ()
        # Qt owns scroll state; retain the full history position while showing
        # the compact latest-call document in the same native view.
        self.detail_offset = 0
        self.reveals: tuple[Reveal, ...] = ()
        self.colors, self.ink = palette(tone(toast.content)), Ink()
        self.layer: Glass | None = None
        self.window = Bubble(self)
        self.badge = SourceBadge(self)
        self.window.setWindowOpacity(0)
        self.label = FeedTitle(self.window)
        self.caption, self.hint = (QLabel(self.window) for _ in range(2))
        for label, face in ((self.label, font(9.5, bold=True)), (self.caption, font(8.5)), (self.hint, font(8.5))):
            label.setFont(face)
            label.setWordWrap(True)
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.hint.linkActivated.connect(self.owner.action_link)
        self.text = TextView(self.window, self.scroll_delta, self.menu)
        self.text.setToolTip(self.window.toolTip())
        self.text.setOpenExternalLinks(False)
        self.text.setOpenLinks(False)
        self.text.anchorClicked.connect(self.owner.action)
        self.details = step_view.StepsView(self.window, self.scroll_details, self.history)
        for text in (self.text, self.details):
            text.verticalScrollBar().valueChanged.connect(self.window.update)
            text.verticalScrollBar().rangeChanged.connect(self.window.update)
        self.stop = IconButton(self.window, Icon.STOP, self.cancel)
        self.stop.clicked.connect(self.cancel)
        self.disclosure = IconButton(self.window, Icon.DISCLOSURE, lambda: self.toggle(animate=False))
        self.disclosure.clicked.connect(self.toggle)
        self.dismiss = IconButton(self.window, Icon.DISMISS, lambda: self.owner.dismiss_card(self.key))
        self.dismiss.clicked.connect(lambda: self.owner.dismiss_card(self.key))
        self.choices: list[QtWidgets.QPushButton] = []
        self.choice_revision = ''
        self.chosen = False
        self.handle = int(self.window.winId())
        windows.make_overlay(self.handle, click_through=False)

    def park(self) -> None:
        """Retain native windows, but detach every interaction from old content.

        AgentToasts owns a bounded pool on Qt's thread. Native window creation
        and glass initialization are measured costs; shutdown alone destroys
        these surfaces. Text, drafts and identified steps do not belong to a slot.
        """
        self.window.hide()
        if self.layer is not None:
            self.layer.hide()
        self.retiring = True
        self.motion = None
        self.content = None
        self.prepared = None
        self.layout = None
        self.expanded = self.hovered = self.tail_pending = False
        self.reveals = ()
        self.spans = ()
        self.text.setExtraSelections([])
        self.text.update_spans((), 1)
        self.details.clear()
        for button in self.choices:
            shiboken6.delete(button)
        self.choices = []
        self.choice_revision = ''
        self.chosen = False

    def bind(self, toast: Toast, width: int) -> None:
        """Assign new logical content to a parked native resource."""
        self.key = toast.key
        self.order = display_order(toast, curated=self.owner.session.triage.enabled)
        self.retiring = False
        self.bounds = None
        self.reader = notification_reading.Waiting(0, self.owner.clock() + notification_reading.START_SECONDS)
        self.detail_offset = 0
        self.page_origin = self.speed = self.spin_angle = 0.0
        self.line_height = round(QFontMetricsF(font()).height() * self.owner.scale * 1.38)
        self.width, self.height, self.maximum, self.right = width, 1, 0, 0
        self.frame = Frame(0, width, 1, 0)
        self.window.setWindowOpacity(0)

    @property
    def y(self) -> float:
        return self.frame.y

    @property
    def alpha(self) -> float:
        return self.frame.alpha

    @property
    def surface_bounds(self) -> Rect:
        bounds = self.bounds if self.bounds is not None else windows.outer_rect(self.handle)
        inset = round(8 * self.owner.scale)
        return Rect(min(bounds.left + inset, bounds.right), min(bounds.top + inset, bounds.bottom), bounds.right, bounds.bottom)

    def history(self) -> None:
        self.owner.show_history()

    def menu(self, point: QPoint) -> None:
        self.text.copy_menu(point, self.history)

    def cancel(self) -> None:
        match self.content:
            case Turn(state=Working()):
                self.owner.agent.stop()
            case Recording() if self.owner.agent.on_recording is not None:
                self.owner.agent.on_recording("stop")
            case _:
                pass

    def choose_solution(self, revision: str, choice: str) -> None:
        if self.closed or self.retiring or not isinstance(self.content, WorkItem) or not isinstance(self.content.item, Assessment):
            return
        callback = self.owner.agent.on_choose_work
        if callback is None or not callback(self.content.item.identity, revision, choice):
            if self.owner.agent.on_problem is not None:
                self.owner.agent.on_problem('That solution could not be started. The proposal may have changed; try again.')
            return
        self.chosen = True
        for button in self.choices:
            button.setEnabled(False)
        selected_button = next((button for button in self.choices if button.objectName() == choice), None)
        if selected_button is not None:
            selected_button.setText('Queued')

    def update_choices(self, content: Content) -> None:
        item = content.item if isinstance(content, WorkItem) and isinstance(content.item, Assessment) else None
        options = notification_text.options(content)
        revision = proposal_revision(item) if item is not None and solutions_for(item) else repr(options)
        if revision == self.choice_revision:
            return
        for button in self.choices:
            shiboken6.delete(button)
        self.choices = []
        self.choice_revision, self.chosen = revision, False
        if item is None:
            for option in options:
                button = QtWidgets.QPushButton(option.text, self.window)
                button.setFont(font(8.5))
                button.setCursor(Qt.CursorShape.PointingHandCursor)
                button.setAccessibleName(option.text)
                button.clicked.connect(lambda checked=False, url=option.link: self.owner.action_link(url))
                self.choices.append(button)
            self.style_choices()
            return
        for index, solution in enumerate(solutions_for(item)):
            button = QtWidgets.QPushButton(solution.label, self.window)
            button.setObjectName(solution.identity)
            button.setFont(font(8.5))
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setAccessibleName(solution.label + (' · Recommended' if index == 0 else ''))
            button.setToolTip(('Recommended: ' if index == 0 else '') + solution.detail)
            button.clicked.connect(lambda checked=False, choice=solution.identity, version=revision: self.choose_solution(version, choice))
            self.choices.append(button)
        self.style_choices()

    def style_choices(self) -> None:
        for index, button in enumerate(self.choices):
            button.setStyleSheet(f'QPushButton {{ color: {self.ink.foreground}; background: transparent; '
                                f'border: 1px solid {self.ink.link if index == 0 else self.ink.secondary}; '
                                'border-radius: 10px; padding: 2px 8px; } '
                                'QPushButton:hover { background: rgba(128,128,160,40); } '
                                'QPushButton:disabled { color: #888888; }')

    def toggle(self, *, animate: bool = True) -> None:
        if self.closed or self.retiring or self.content is None or not notification_text.expandable(self.content):
            return
        self.owner.toggle_card(self, animate=animate)

    def scroll_details(self, delta: int) -> None:
        if not self.closed and self.expanded:
            scroll = self.details.verticalScrollBar()
            scroll.setValue(scroll.value() + round(-delta / 120 * self.line_height / self.owner.scale * 3))
            self.detail_offset = self.details.offset
            self.owner.set_hover(self.key, True)

    def check_pointer(self) -> None:
        if not self.closed and self.bounds is not None:
            x, y = self.owner.desktop.cursor_position()
            self.owner.set_hover(self.key, self.bounds.contains(x, y))

    def scroll_delta(self, delta: int) -> None:
        if not delta or self.closed or self.prepared is None:
            return
        scroll = self.text.verticalScrollBar()
        scroll.setValue(scroll.value() + round(-delta / 120 * self.line_height / self.owner.scale * 3))
        self.reader = notification_reading.Paused(self.text.offset * self.owner.scale)
        self.page_origin = self.reader.offset
        self.owner.set_hover(self.key, True)
        self.owner.tick()

    def overflow(self) -> int:
        if self.prepared is None or self.layout is None:
            return 0
        return max(0, self.prepared[2].body_height - self.layout.body_height)

    def needs_reading(self) -> bool:
        return not self.retiring and not isinstance(self.content, (Recording, WorkItem)) and self.reader.offset < self.overflow()

    def read(self, now: float, *, paused: bool, smooth: bool) -> bool:
        if isinstance(self.content, (Recording, WorkItem)) or self.prepared is None or self.layout is None:
            return False
        limit = self.overflow()
        self.reader = notification_reading.advance(self.reader, now, limit, self.speed, paused=paused)
        if limit and not paused and self.text.height() > 1:
            offset = notification_reading.displayed(
                self.reader.offset, limit, self.layout.body_height, self.line_height, smooth=smooth, origin=self.page_origin)
            self.text.verticalScrollBar().setValue(round(offset / self.owner.scale))
        return not isinstance(self.reader, notification_reading.Finished)

    def apply_style(self, content: Content, preference: appearance.Preference) -> None:
        source = origin_item(content)
        app = source.origins[0].app if source is not None and source.origins else None
        look = (tone(content), app, preference, self.frost)
        if self.look == look:
            return
        self.look = look
        self.colors, self.ink = palette(tone(content), app), Ink()
        if isinstance(preference, appearance.Contrast):
            self.colors = Palette(preference.background, preference.foreground, preference.foreground, preference.background)
            self.ink = Ink(*(preference.foreground for _ in range(4)))
        elif preference is appearance.Material.GLASS and self.frost is appearance.Frost.BRIGHT:
            self.ink = Ink("#202435", "#3b3d50", "#234782", "#8e3144")
        if preference is appearance.Material.GLASS and self.layer is None and self.owner.loop.composition is not None:
            try:
                self.layer = self.create_glass(self.owner.loop.composition)
            except OSError as error:
                log_view(f"Rounded glass unavailable; using the solid material: {error}")
        self.glass = preference is appearance.Material.GLASS and self.layer is not None
        if self.layer is not None:
            self.layer.color(self.colors.tint, .82 if self.frost is appearance.Frost.SMOKED else .22)
            if not self.glass:
                self.layer.hide()
        if not self.glass and not isinstance(preference, appearance.Contrast):
            self.ink = Ink()
        title_size = TITLE_SIZE if isinstance(content, Turn) or (isinstance(content, WorkItem) and isinstance(content.item, Assessment)) else 9.5
        for label, color in ((self.label, self.ink.foreground), (self.caption, self.ink.secondary), (self.hint, self.ink.secondary)):
            face = (f"font-size: {title_size}pt; "
                    "font-weight: 600; font-family: 'Segoe UI';") if label is self.label else ''
            label.setStyleSheet(f"background: transparent; color: {color}; padding: 0; margin: 0; border: none; {face}")
        for button in (self.stop, self.disclosure, self.dismiss):
            button.ink = self.ink.foreground
            button.update()
        self.style_choices()
        self.text.recolor(self.ink)
        self.details.recolor(self.ink)
        self.badge.update()
        self.window.update()
        if self.bounds is not None and self.layer is not None and self.glass:
            self.layer.position(self.surface_bounds, self.owner.scale, self.alpha)
            if self.window.isVisible():
                self.layer.show(self.handle)

    def measure(self, content: Content, width: int) -> Prepared:
        if self.prepared is None or self.prepared[:2] != (content, width):
            self.prepared = (content, width, self.owner.measure.prepare(content, width, expanded=self.expanded))
        return self.prepared[2]

    def render_heading(self, content: Content, prepared: Prepared) -> None:
        user = tone(content) is Tone.USER
        compact = isinstance(content, WorkItem) or (isinstance(content, Turn) and isinstance(content.state, Settled))
        source = origin_item(content)
        curated = source is not None and isinstance(source.item, Assessment)
        self.label.flow = curated or isinstance(content, Turn)
        self.label.expanded = self.expanded
        self.label.setFont(font(TITLE_SIZE if self.label.flow else 9.5, bold=True))
        self.label.setObjectName('workItemTitle' if curated else '')
        self.label.setText(notification_text.title_text(content))
        self.label.setToolTip(escape(self.label.text()) if curated else '')
        self.caption.setText(prepared.caption)
        self.label.setVisible(self.label.flow or (not user and not compact))
        self.caption.setVisible(not user and bool(prepared.caption))

    def render(self, content: Content, maximum_width: int, maximum: int, preference: appearance.Preference) -> None:
        prepared = self.measure(content, maximum_width)
        width = prepared.width
        source = origin_item(content)
        app = source.origins[0].app if source is not None and source.origins else None
        if (content == self.content and (width, maximum) == (self.width, self.maximum)
                and self.look == (tone(content), app, preference, self.frost) and self.layout is not None):
            return
        previous = self.content
        self.layout = self.owner.measure.layout(prepared, width, maximum)
        self.content, self.width, self.maximum, self.height = content, width, maximum, self.layout.height
        self.apply_style(content, preference)
        user = tone(content) is Tone.USER
        self.render_heading(content, prepared)
        self.badge.source(content)
        self.update_choices(content)
        self.hint.setTextFormat(Qt.TextFormat.PlainText)
        self.hint.setText(self.layout.hint)
        self.hint.setAlignment((Qt.AlignmentFlag.AlignRight if user else Qt.AlignmentFlag.AlignLeft) | Qt.AlignmentFlag.AlignVCenter)
        self.stop.setVisible(can_stop(content))
        self.dismiss.setVisible(not user)
        self.stop.setEnabled(not (isinstance(content, Turn) and isinstance(content.state, Working) and content.state.phase is Busy.STOPPING)
                             and not (isinstance(content, Recording) and content.state.phase == "stopping"))
        source = origin_item(content)
        curated = source is not None and isinstance(source.item, Assessment)
        self.disclosure.setVisible(notification_text.expandable(content) and not curated)
        self.window.setCursor(Qt.CursorShape.PointingHandCursor if curated else Qt.CursorShape.ArrowCursor)
        self.window.setAccessibleDescription(('Click to hide details' if self.expanded else 'Click to expand details') if curated else '')
        self.disclosure.expanded = self.expanded
        section = 'details' if isinstance(content, WorkItem) else 'steps'
        self.disclosure.setAccessibleName(('Hide ' if self.expanded else 'Show ') + section)
        self.disclosure.setToolTip(self.disclosure.accessibleName() + (' · ' + caption(content) if caption(content) else ''))
        self.disclosure.update()
        text_width = max(1, prepared.text_width / self.owner.scale)
        self.details.present(content, text_width, expanded=self.expanded)
        if prepared.spans != self.spans:
            offset = units("".join(span.text for span in self.spans))
            self.spans = prepared.spans
            self.text.update_spans(prepared.spans, text_width)
            self.speed = notification_reading.pace("".join(span.text for span in prepared.spans), prepared.body_height, self.line_height)
            before, after = notification_text.answer(previous), notification_text.answer(content)
            if (before is not None and after is not None and before.identity == after.identity and after.state is not StreamState.INTERRUPTED
                    and self.owner.motion_enabled() and not isinstance(preference, appearance.Contrast)):
                end = units("".join(span.text for span in self.spans))
                if end > offset:
                    self.reveals = (*self.reveals[-11:], Reveal(offset, end, self.owner.clock()))
        self.place_content(self.frame.width if previous is not None else width, self.frame.height if previous is not None else self.height,
                           self.frame.details if previous is not None else self.layout.details_height)
        if isinstance(content, Recording):
            self.tail_pending = True  # Follow the newest transcript after Qt resolves the final viewport.
        self.window.setAccessibleName(f"{heading(content)}. {prepared.caption}".strip())
        self.window.update()

    def fade_text(self, now: float, *, animate: bool) -> bool:
        self.reveals = tuple(reveal for reveal in self.reveals if animate and now - reveal.started < REVEAL_SECONDS)
        selections: list[QTextEdit.ExtraSelection] = []
        start, end = QColor(self.ink.secondary), QColor(self.ink.foreground)
        for reveal in self.reveals:
            amount = max(0.0, min(1.0, (now - reveal.started) / REVEAL_SECONDS))
            selection = QTextEdit.ExtraSelection()
            selection.cursor = QTextCursor(self.text.document())
            selection.cursor.setPosition(min(reveal.start, self.text.document().characterCount() - 1))
            selection.cursor.setPosition(min(reveal.end, self.text.document().characterCount() - 1), QTextCursor.MoveMode.KeepAnchor)
            pairs = ((start.red(), end.red()), (start.green(), end.green()), (start.blue(), end.blue()))
            color = QColor(*(round(a + (b - a) * amount) for a, b in pairs))
            selection.format = QTextCharFormat()
            selection.format.setForeground(color)
            selections.append(selection)
        self.text.setExtraSelections(selections)
        return bool(self.reveals)

    def match_background(self, sample: appearance.Backdrop, preference: appearance.Preference) -> None:
        if not self.glass or self.bounds != sample.bounds or self.content is None or self.retiring:
            return
        if sample.frost is not self.frost:
            self.frost = sample.frost
            self.apply_style(self.content, preference)

    def place_heading(self, wide: float, header: float, controls: int, caption: str) -> None:
        label_width = max(1, round(wide) - INSET * 2 - self.badge.width() - controls)
        caption_height = round(QFontMetricsF(font(8.5)).height()) if caption else 0
        self.label.setGeometry(INSET + self.badge.width(), 14, label_width, max(1, round(header - 22) - caption_height))
        if self.label.flow:
            left = INSET + self.badge.width()
            title_width = heading_width(round(wide), self.badge.width(), stopping=not self.stop.isHidden(), disclosing=not self.disclosure.isHidden())
            self.label.setGeometry(left, 16, title_width, max(1, round(header - 22)))
        self.caption.setGeometry(INSET + self.badge.width(), round(header - 8) - caption_height, label_width, max(1, caption_height))

    def place_content(self, width: float, height: float, details: float) -> None:
        if self.layout is None or self.prepared is None:
            return
        scale = self.owner.scale
        layout, prepared = self.layout, self.prepared[2]
        wide = width / scale
        header = prepared.header_height / scale
        right = round(wide) - INSET
        controls = 0
        if not self.dismiss.isHidden():
            self.dismiss.setGeometry(round(wide) - 32, 16, 24, 24)
            right -= 26
            controls += 26
        if not self.stop.isHidden():
            self.stop.setGeometry(right - 28, 14, 28, max(28, round(header - 20)))
            right -= 32
            controls += 32
        if not self.disclosure.isHidden():
            if isinstance(self.content, WorkItem) or (isinstance(self.content, Turn) and prepared.header_height <= 36 * scale):
                self.disclosure.setGeometry(right - 22, 14, 22, 20)
            else:
                self.disclosure.setGeometry(right - 28, 14, 28, max(28, round(header - 20)))
            right -= 26
            controls += 26
        self.badge.move(0, 0)
        self.place_heading(wide, header, controls, prepared.caption)
        detail_height = max(0, min(details, height - prepared.header_height - layout.hint_height - prepared.padding))
        top = prepared.header_height + detail_height
        body_height = max(0, min(layout.body_height, height - top - layout.hint_height - prepared.padding))
        text_width = max(1, round(wide) - INSET * 2 - 8)
        for text, start, visible in ((self.details, prepared.header_height, detail_height), (self.text, top, body_height)):
            if visible > TEXT_PADDING * 2 * scale:
                offset = self.detail_offset if text is self.details and self.expanded else text.offset
                text.setGeometry(INSET + 8, round(start / scale) + TEXT_PADDING, text_width, max(1, round(visible / scale) - TEXT_PADDING * 2))
                text.fit_width()
                text.show()
                text.verticalScrollBar().setValue(offset)
            else:
                text.hide()
        footer_top = round((top + body_height) / scale)
        if self.choices:
            self.hint.hide()
            geometry = choice_geometry(tuple(button.text() for button in self.choices), text_width)
            for button, (x, y, button_width) in zip(self.choices, geometry, strict=True):
                button.setGeometry(INSET + 8 + x, footer_top + y, button_width, 24)
                button.show()
            footer_top += geometry[-1][1] + 30
        elif layout.hint_height:
            self.hint.setGeometry(INSET + 8, footer_top, text_width, max(1, round(layout.hint_height / scale) - 4))
            self.hint.show()
        else:
            self.hint.hide()
        self.window.update()

    def pulse(self, now: float) -> None:
        self.spin_angle = (90 - now * 300) % 360
        self.details.pulse(self.spin_angle)
        self.window.update()
        self.badge.update()

    def position(self, right: int, frame: Frame) -> None:
        # Native bounds can differ by a pixel after Qt rounds at fractional DPI.
        # Compare the requested frame, or an idle tick will undo that rounding
        # repeatedly and keep the shared native event queue busy.
        if self.bounds is not None and self.right == right and self.frame == frame:
            return
        bounds = Rect(right - round(frame.width), round(frame.y), right, round(frame.y + frame.height))
        if (self.bounds is None or (self.bounds.width, self.bounds.height) != (bounds.width, bounds.height)
                or self.frame.details != frame.details):
            self.place_content(bounds.width, bounds.height, frame.details)
        if self.bounds != bounds:
            self.move(self.handle, bounds)
            self.bounds = bounds
        if self.alpha != frame.alpha:
            self.window.setWindowOpacity(max(0.0, min(1.0, frame.alpha)))
        self.right, self.frame = right, frame

    def target(self, y: float, alpha: float, now: float, *, animate: bool, retarget: bool = False) -> None:
        end = Frame(y, self.width, self.height, alpha, self.layout.details_height if self.layout is not None else self.frame.details)
        if not animate:
            self.motion = None
            self.position(self.right, end)
            return
        if not retarget and self.motion is not None and self.motion.end == end:
            return
        current = self.motion.sample(now) if self.motion is not None else self.frame
        self.motion = Motion(current, end, now) if current != end else None

    def reveal(self) -> None:
        self.window.show()
        windows.show_quietly(self.handle, True)
        if self.layer is not None and self.glass:
            self.layer.position(self.surface_bounds, self.owner.scale, self.alpha)
            self.layer.show(self.handle)

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.window.close()
        if self.layer is not None:
            self.layer.close()
        shiboken6.delete(self.window)
