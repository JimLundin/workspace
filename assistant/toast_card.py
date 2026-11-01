"""One rounded conversation surface with independent steps and attached result."""

import math
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum, auto
from html import escape
from typing import Protocol

lazy import shiboken6
lazy from PySide6 import QtCore, QtWidgets
lazy from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt
lazy from PySide6.QtGui import (
    QContextMenuEvent,
    QEnterEvent,
    QFontMetricsF,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QTextCharFormat,
    QTextCursor,
)
lazy from PySide6.QtWidgets import QAbstractButton, QLabel, QTextEdit, QWidget

from assistant import notification_reading, notification_text, step_view, toast_stack
from assistant.feed_origin import App
from assistant.notifications import (
    REVEAL_SECONDS,
    Busy,
    Content,
    Entry,
    Key,
    Recording,
    Response,
    Settled,
    Toast,
    Tone,
    Turn,
    Working,
    can_stop,
    caption,
    heading,
    hint,
    order_of,
    spinning,
    tone,
)
from assistant.qt_runtime import prepare
from assistant.rich_text import Span
from assistant.toast_stack import Frame, Moving
from assistant.ui_components import bubble
from assistant.ui_components.appearance import GlassLook, Scheme, Shade
from assistant.ui_components.bubble import (
    ACTION,
    ACTIONS_TOP,
    BADGE,
    BOTTOM,
    CONTROL,
    CONTROL_GAP,
    LEFT,
    RIGHT,
    TEXT_LEFT,
    TOP,
    Badge,
    BadgeSize,
    FeedTitle,
    Look,
    Spinning,
    action_face,
    action_geometry,
    action_style,
    meta_face,
    paint_badge,
    paint_card,
    title_height,
    title_width,
)
from assistant.ui_components.canvas_jump import CanvasJumpButton
from assistant.ui_components.press_feedback import paint_feedback
from assistant.ui_components.text import BODY, Document, TextView, color, face, line_height, units
from assistant.vector_icons import icon
from assistant.view_publication import log_view
from automation.presentation import StreamState
from winapi import appearance, windows
from winapi.composition import DesktopComposition, Glass
from winapi.shapes import Rect

prepare()

SECTION = 4  # logical padding above and below each text region
CANVAS_ROW = ACTION + 8  # one persistent canvas action below the text
THUMB = 6  # the overlay scroll bar's thumb, 2 px inside the card's trailing edge


@dataclass(frozen=True, slots=True)
class Finish:
    """What the desktop asks a card to look like: the material preference and Windows' app scheme."""

    preference: appearance.Preference
    scheme: Scheme


@dataclass(frozen=True, slots=True)
class Prepared:
    width: int
    spans: tuple[Span, ...]
    canvas_actions: tuple[Span, ...]
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


def _text_height(text: str, width: float) -> float:
    metrics = QFontMetricsF(meta_face())
    return metrics.boundingRect(QRectF(0, 0, max(1, width), 10000), Qt.TextFlag.TextWordWrap.value, text).height() if text else 0


def _meta_height(text: str) -> int:
    return math.ceil(QFontMetricsF(meta_face()).height()) if text else 0


def _controls(content: Content) -> int:
    """Dismiss, Stop and the disclosure sit at the head's trailing edge."""
    user = tone(content) is Tone.USER
    return (0 if user else 1) + (1 if can_stop(content) else 0) + (1 if notification_text.expandable(content) else 0)


def _title(content: Content) -> str:
    return notification_text.title_text(content) if _turn(content) else heading(content)


class Measure:
    __slots__ = ("body", "details", "scale")

    def __init__(self) -> None:
        self.body, self.details = Document(), step_view.Measure()
        self.scale = 1.0

    def prepare(self, content: Content, maximum: int, *, expanded: bool = False) -> Prepared:
        scale = self.scale
        user = tone(content) is Tone.USER
        compact = _settled_turn(content)
        maximum_width = min(maximum / scale, 280 if user else maximum / scale)
        presentation = notification_text.bubble_text(notification_text.spans(content))
        spans = presentation.body
        details = notification_text.step_blocks(content, expanded=expanded)
        meta, footer = "" if compact else caption(content), hint(content)
        match content:
            case Entry() | Turn():
                # Agent questions use the bubble's voice tooltip, with no input footer.
                footer = ""
            case Response() | Recording():
                pass
        body_padding = TEXT_LEFT + RIGHT
        # The feed has one column width. Only the person's speech uses a smaller
        # card; standalone replies must match conversation and proposal cards.
        width = maximum_width
        if user:
            body_width = self.body.intrinsic_width(spans, max(1, maximum_width - body_padding))
            width = min(maximum_width, max(120, body_width + body_padding))
        labels = tuple(span.text for span in notification_text.options(content))
        logical = round(math.ceil(width * scale) / scale)
        text_width = max(1, logical - body_padding)
        body_height = self.body.load(spans, text_width) + SECTION * 2 if spans else 0
        details_height = self.details.total(details, text_width) + SECTION * 2 if details else 0
        label_width = title_width(logical, _controls(content))
        # Collapsed turns elide their title to one line; other headings wrap.
        title = title_height(_title(content), label_width, expanded=expanded or not _turn(content))
        header = TOP + max(BADGE, title + _meta_height(meta))
        footer_height = _text_height(footer, text_width) + SECTION * 2 if footer else 0
        if labels:
            geometry = action_geometry(labels, text_width)
            footer_height = ACTIONS_TOP + geometry[-1][1] + ACTION
            footer = ""
        footer_height += CANVAS_ROW * len(presentation.canvas_actions)
        return Prepared(
            math.ceil(width * scale),
            spans,
            presentation.canvas_actions,
            math.ceil(body_height * scale),
            math.ceil(header * scale),
            math.floor(label_width * scale),
            footer,
            math.ceil(footer_height * scale),
            meta,
            details,
            math.ceil(details_height * scale),
            round(200 * scale),
            round(BOTTOM * scale),
            math.floor(text_width * scale),
        )

    def fit_body(self, document: Document, spans: tuple[Span, ...], width: int, available: int) -> int:
        if not spans:
            return 0
        document.load(spans, max(1, width / self.scale))
        fitted = document.fit(available / self.scale - SECTION * 2)
        return math.ceil((fitted + SECTION * 2) * self.scale) if fitted else 0

    def layout(self, prepared: Prepared, width: int, maximum: int) -> Layout:
        available = max(0, maximum - prepared.header_height - prepared.hint_height - prepared.padding)
        budget = min(prepared.details_limit, max(0, available - min(prepared.body_height, available // 2)))
        text_width = max(1, prepared.text_width + width - prepared.width)
        details = min(prepared.details_height, budget)
        available -= details
        body = self.fit_body(self.body, prepared.spans, text_width, available) if prepared.body_height > available else prepared.body_height
        return Layout(
            details, body, prepared.hint, prepared.hint_height, prepared.header_height + details + body + prepared.hint_height + prepared.padding
        )

    def close(self) -> None:
        self.body.close()
        self.details.close()


class CardOwner(Protocol):
    """What one card reads from, and asks of, the stack that owns it."""

    @property
    def scale(self) -> float: ...

    @property
    def measure(self) -> Measure: ...

    @property
    def composition(self) -> DesktopComposition | None: ...

    def clock(self) -> float: ...
    def animations(self) -> bool: ...
    def cursor_position(self) -> tuple[int, int]: ...
    def dismiss_card(self, key: Key) -> None: ...
    def toggle_card(self, selected: Card, *, animate: bool) -> None: ...
    def set_hover(self, key: Key, *, inside: bool) -> None: ...
    def action(self, url: QtCore.QUrl) -> None: ...
    def action_link(self, link: str) -> None: ...
    def show_history(self) -> None: ...
    def stop_agent(self) -> None: ...
    def stop_recording(self) -> None: ...
    def tick(self) -> None: ...


class Icon(Enum):
    STOP = auto()
    DISCLOSURE = auto()
    DISMISS = auto()


class IconButton(QAbstractButton):
    __slots__ = ("controls", "expanded", "key_click", "kind")

    def __init__(self, parent: QWidget, kind: Icon, key_click: Callable[[], None]) -> None:
        super().__init__(parent)
        self.kind = kind
        self.key_click = key_click
        self.expanded = False
        self.controls = bubble.look(appearance.Material.SOLID, Scheme.DARK).controls
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName("Dismiss item" if kind is Icon.DISMISS else "Stop agent" if kind is Icon.STOP else "Show steps")
        self.setToolTip(self.accessibleName())

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        paint_feedback(self, painter, self.controls)
        ink = self.controls.ink
        painter.setOpacity(ink.opacity * (0.45 if not self.isEnabled() else 1))
        cx, cy = self.width() // 2, self.height() // 2
        match self.kind:
            case Icon.STOP:
                name = "stop"
            case Icon.DISMISS:
                name = "close"
            case Icon.DISCLOSURE:
                name = "down"
                if self.expanded:
                    painter.translate(cx * 2, cy * 2)
                    painter.rotate(180)
        icon(name, ink.color).paint(painter, QRect(cx - 8, cy - 8, 16, 16))

    def enterEvent(self, event: QEnterEvent) -> None:
        super().enterEvent(event)
        self.update()

    def leaveEvent(self, event: QtCore.QEvent) -> None:
        super().leaveEvent(event)
        self.update()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.setDown(True)
            event.accept()
        else:
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.setDown(False)
            if self.isEnabled() and not event.isAutoRepeat():
                self.key_click()
            event.accept()
        else:
            super().keyReleaseEvent(event)


class SourceBadge(QWidget):
    """The card's app badge. Every feed card is Workspace's own: the agent's direction, never an app arrival."""

    __slots__ = ("card",)

    def __init__(self, card: Card) -> None:
        super().__init__(card.window)
        self.card = card
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def source(self, content: Content) -> None:
        names = App.WORKSPACE.value + (" · You" if tone(content) is Tone.USER else "")
        self.setAccessibleName("From " + names)
        self.setToolTip(escape(names))
        self.setGeometry(LEFT, TOP, BADGE, BADGE)
        self.show()
        self.raise_()
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        content = self.card.content
        working = content is not None and spinning(content)
        painter = QPainter(self)
        mark = Spinning(App.WORKSPACE, self.card.spin_angle) if working else App.WORKSPACE
        paint_badge(painter, QPointF(), Badge(mark, BadgeSize.CARD))


class Bubble(QWidget):
    __slots__ = ("card",)

    def __init__(self, card: Card) -> None:
        super().__init__()
        self.card = card
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setWindowTitle("Workspace · Agent notification")
        self.setToolTip("Hold the agent voice-to-text button (N) to reply; release to send.")

    def paintEvent(self, event: QPaintEvent) -> None:
        card = self.card
        painter = QPainter(self)
        paint_card(painter, QRectF(self.rect()), card.style.surface)
        if not card.hovered:
            return
        # Overlay scroll bars: only while the pointer can scroll, never a permanent track.
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color(card.style.thumb))
        for text in (card.text, card.details):
            scroll = text.verticalScrollBar()
            if not text.isHidden() and scroll.maximum() > 0:
                height = text.height()
                total = height + scroll.maximum()
                length = min(height, max(24, height * height / total))
                start = text.y() + (height - length) * scroll.value() / scroll.maximum()
                painter.drawRoundedRect(QRectF(self.width() - 4 - THUMB, start, THUMB, length), THUMB / 2, THUMB / 2)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        prepared = self.card.prepared
        if (
            event.button() is Qt.MouseButton.LeftButton
            and prepared is not None
            and event.position().y() < prepared[2].header_height / self.card.owner.scale
        ):
            self.card.toggle()
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        self.card.menu(event.globalPos())
        event.accept()


def _glass(composition: DesktopComposition) -> Glass:
    return composition.glass()


class Card:
    __slots__ = (
        "__weakref__",
        "badge",
        "bounds",
        "canvas_actions",
        "caption",
        "choice_options",
        "choices",
        "closed",
        "content",
        "create_glass",
        "detail_offset",
        "details",
        "disclosure",
        "dismiss",
        "expanded",
        "finish",
        "frame",
        "glass",
        "handle",
        "height",
        "hint",
        "hovered",
        "key",
        "label",
        "layer",
        "layout",
        "line_height",
        "maximum",
        "measurement",
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
        "style",
        "tail_pending",
        "text",
        "width",
        "window",
    )

    def __init__(
        self,
        owner: CardOwner,
        toast: Toast,
        width: int,
        *,
        move: Callable[[int, Rect], None] = windows.move,
        glass: Callable[[DesktopComposition], Glass] | None = None,
    ) -> None:
        # Geometry and glass creation are the two native effects owned by a card;
        # injected adapters retain real widgets and the same scene lifetime.
        self.move, self.create_glass = move, _glass if glass is None else glass
        self.owner: CardOwner = owner
        # The stack retains the shared Qt measurement lifetime; the card binds
        # that dependency directly without reaching through its owner.
        self.measurement: Measure = owner.measure
        self.key, self.order = toast.key, (0, *order_of(toast))
        self.content: Content | None = None
        self.prepared: tuple[Content, int, Prepared] | None = None
        self.layout: Layout | None = None
        self.bounds: Rect | None = None
        self.finish: Finish | None = None
        self.glass = self.closed = self.hovered = self.retiring = self.expanded = self.tail_pending = False
        self.motion: Moving | None = None
        self.reader: notification_reading.State = notification_reading.Waiting(0, owner.clock() + notification_reading.START_SECONDS)
        self.page_origin = self.speed = self.spin_angle = 0.0
        self.line_height = round(line_height(face(BODY)) * owner.scale)
        self.width, self.height, self.maximum, self.right = width, 1, 0, 0
        self.frame = Frame(0, width, 1, 0)
        self.spans: tuple[Span, ...] = ()
        # Qt owns scroll state; retain the full history position while showing
        # the compact latest-call document in the same native view.
        self.detail_offset = 0
        self.reveals: tuple[Reveal, ...] = ()
        self.style: Look = bubble.look(appearance.Material.SOLID, Scheme.DARK)
        self.layer: Glass | None = None
        self.window = Bubble(self)
        self.badge = SourceBadge(self)
        self.window.setWindowOpacity(0)
        self.label = FeedTitle(self.window)
        self.caption, self.hint = (QLabel(self.window) for _ in range(2))
        for label in (self.caption, self.hint):
            label.setFont(meta_face())
        for label in (self.label, self.caption, self.hint):
            label.setWordWrap(True)
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.text = TextView(self.window, self.scroll_delta, self.menu)
        self.text.setToolTip(self.window.toolTip())
        self.connect_actions()
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
        self.canvas_actions: tuple[tuple[Span, CanvasJumpButton], ...] = ()
        self.choices: tuple[QtWidgets.QPushButton, ...] = ()
        self.choice_options: tuple[Span, ...] = ()
        self.handle = int(self.window.winId())
        windows.make_overlay(self.handle, click_through=False)

    def connect_actions(self) -> None:
        self.hint.linkActivated.connect(self.owner.action_link)
        self.text.setOpenExternalLinks(False)
        self.text.setOpenLinks(False)
        self.text.anchorClicked.connect(self.owner.action)

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
        self.update_canvas_actions(())
        self.text.setExtraSelections([])
        self.text.update_spans((), 1)
        self.details.clear()
        for button in self.choices:
            shiboken6.delete(button)
        self.choices = ()
        self.choice_options = ()

    def bind(self, toast: Toast, width: int) -> None:
        """Assign new logical content to a parked native resource."""
        self.key = toast.key
        self.order = (0, *order_of(toast))
        self.retiring = False
        self.bounds = None
        self.reader = notification_reading.Waiting(0, self.owner.clock() + notification_reading.START_SECONDS)
        self.detail_offset = 0
        self.page_origin = self.speed = self.spin_angle = 0.0
        self.line_height = round(line_height(face(BODY)) * self.owner.scale)
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
        """The glass fills the card's whole window; the badge sits inside it."""
        return self.bounds if self.bounds is not None else windows.outer_rect(self.handle)

    def history(self) -> None:
        self.owner.show_history()

    def menu(self, point: QPoint) -> None:
        self.text.copy_menu(point, self.history)

    def cancel(self) -> None:
        match self.content:
            case Turn(state=Working()):
                self.owner.stop_agent()
            case Recording():
                self.owner.stop_recording()
            case _:
                pass

    def update_choices(self, content: Content) -> None:
        options = notification_text.options(content)
        if options == self.choice_options:
            return
        for button in self.choices:
            shiboken6.delete(button)
        self.choice_options = options

        def create(index: int, option: Span) -> QtWidgets.QPushButton:
            button = QtWidgets.QPushButton(option.text, self.window)
            button.setFont(action_face(primary=not index))
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setAccessibleName(option.text)
            button.clicked.connect(self.link_action(option.link))
            return button

        # The card owns the native buttons; the first option is the primary action.
        self.choices = tuple(create(index, option) for index, option in enumerate(options))
        self.style_choices()

    def update_canvas_actions(self, actions: tuple[Span, ...]) -> None:
        if actions == tuple(span for span, _button in self.canvas_actions):
            return
        for _span, old in self.canvas_actions:
            shiboken6.delete(old)

        def create(span: Span) -> tuple[Span, CanvasJumpButton]:
            button = CanvasJumpButton(self.window, self.style.controls)
            button.clicked.connect(self.link_action(span.link))
            return span, button

        # The card owns native button lifetimes; observations and membership
        # stay immutable. Parked cards discard their old destinations.
        self.canvas_actions = tuple(create(span) for span in actions)

    def link_action(self, url: str) -> Callable[[object], None]:
        def clicked(_checked: object) -> None:
            self.owner.action_link(url)

        return clicked

    def style_choices(self) -> None:
        for index, button in enumerate(self.choices):
            button.setStyleSheet(action_style(self.style.controls, primary=not index))

    def toggle(self, *, animate: bool = True) -> None:
        if self.closed or self.retiring or self.content is None or not notification_text.expandable(self.content):
            return
        self.owner.toggle_card(self, animate=animate)

    def scroll_details(self, delta: int) -> None:
        if not self.closed and self.expanded:
            scroll = self.details.verticalScrollBar()
            scroll.setValue(scroll.value() + round(-delta / 120 * self.line_height / self.owner.scale * 3))
            self.detail_offset = self.details.offset
            self.owner.set_hover(self.key, inside=True)

    def check_pointer(self) -> None:
        if not self.closed and self.bounds is not None:
            x, y = self.owner.cursor_position()
            self.owner.set_hover(self.key, inside=self.bounds.contains(x, y))

    def scroll_delta(self, delta: int) -> None:
        if not delta or self.closed or self.prepared is None:
            return
        scroll = self.text.verticalScrollBar()
        scroll.setValue(scroll.value() + round(-delta / 120 * self.line_height / self.owner.scale * 3))
        self.reader = notification_reading.Paused(self.text.offset * self.owner.scale)
        self.page_origin = self.reader.offset
        self.owner.set_hover(self.key, inside=True)
        self.owner.tick()

    def overflow(self) -> int:
        if self.prepared is None or self.layout is None:
            return 0
        return max(0, self.prepared[2].body_height - self.layout.body_height)

    def needs_reading(self) -> bool:
        return not self.retiring and not _recording(self.content) and self.reader.offset < self.overflow()

    def read(self, now: float, *, paused: bool, smooth: bool) -> bool:
        if _recording(self.content) or self.prepared is None or self.layout is None:
            return False
        limit = self.overflow()
        self.reader = notification_reading.advance(self.reader, now, limit, self.speed, paused=paused)
        if limit and not paused and self.text.height() > 1:
            offset = notification_reading.displayed(
                self.reader.offset, limit, self.layout.body_height, self.line_height, smooth=smooth, origin=self.page_origin
            )
            self.text.verticalScrollBar().setValue(round(offset / self.owner.scale))
        match self.reader:
            case notification_reading.Finished():
                return False
            case notification_reading.Waiting() | notification_reading.Scrolling() | notification_reading.Paused():
                return True

    def apply_style(self, finish: Finish) -> None:
        if self.finish == finish:
            return
        self.finish = finish
        preference = finish.preference
        composition = self.owner.composition
        if preference is appearance.Material.GLASS and self.layer is None and composition is not None:
            try:
                self.layer = self.create_glass(composition)
            except OSError as error:
                log_view(f"Rounded glass unavailable; using the solid material: {error}")
        self.glass = preference is appearance.Material.GLASS and self.layer is not None
        # Without a composition layer, requested glass falls back to the solid material.
        self.style = bubble.look(preference if self.glass or _contrast(preference) else appearance.Material.SOLID, finish.scheme)
        match self.style.surface:
            case GlassLook(veil=veil) if self.layer is not None:
                self.layer.color(veil.color, veil.opacity)
            case _:
                if self.layer is not None:
                    self.layer.hide()
        ink = self.style.text
        for label, shade in ((self.label, ink.ink), (self.caption, ink.quiet), (self.hint, ink.quiet)):
            label.setStyleSheet(f"background: transparent; color: {shade.css}; padding: 0; margin: 0; border: none;")
        for button in (self.stop, self.disclosure, self.dismiss):
            button.controls = self.style.controls
            button.update()
        self.style_choices()
        for _span, canvas_button in self.canvas_actions:
            canvas_button.recolor(self.style.controls)
        self.text.recolor(ink)
        self.details.recolor(ink)
        self.badge.update()
        self.window.update()
        if self.bounds is not None and self.layer is not None and self.glass:
            self.layer.position(self.surface_bounds, self.owner.scale, self.alpha)
            if self.window.isVisible():
                self.layer.show(self.handle)

    def measure(self, content: Content, width: int) -> Prepared:
        if self.prepared is None or self.prepared[0] != content or self.prepared[1] != width:
            self.prepared = (content, width, self.measurement.prepare(content, width, expanded=self.expanded))
        return self.prepared[2]

    def render_heading(self, content: Content, prepared: Prepared) -> None:
        # Collapsed turns elide their title to one line; other headings wrap.
        self.label.expanded = self.expanded or not _turn(content)
        self.label.setText(_title(content))
        self.caption.setText(prepared.caption)
        self.label.show()
        self.caption.setVisible(bool(prepared.caption))

    def render(self, content: Content, maximum_width: int, maximum: int) -> None:
        """Lay out content within the stack's allotment; `apply_style` has already chosen its look."""
        prepared = self.measure(content, maximum_width)
        width = prepared.width
        if content == self.content and (width, maximum) == (self.width, self.maximum) and self.layout is not None:
            return
        previous = self.content
        self.layout = self.measurement.layout(prepared, width, maximum)
        self.content, self.width, self.maximum, self.height = content, width, maximum, self.layout.height
        user = tone(content) is Tone.USER
        self.render_heading(content, prepared)
        self.badge.source(content)
        self.update_choices(content)
        self.update_canvas_actions(prepared.canvas_actions)
        self.hint.setTextFormat(Qt.TextFormat.PlainText)
        self.hint.setText(self.layout.hint)
        self.stop.setVisible(can_stop(content))
        self.dismiss.setVisible(not user)
        self.stop.setEnabled(not _stopping(content))
        self.disclosure.setVisible(notification_text.expandable(content))
        self.disclosure.expanded = self.expanded
        self.disclosure.setAccessibleName(("Hide " if self.expanded else "Show ") + "steps")
        self.disclosure.setToolTip(self.disclosure.accessibleName() + (" · " + caption(content) if caption(content) else ""))
        self.disclosure.update()
        text_width = max(1, prepared.text_width / self.owner.scale)
        self.details.present(content, text_width, expanded=self.expanded)
        if prepared.spans != self.spans:
            offset = units("".join(span.text for span in self.spans))
            self.spans = prepared.spans
            self.text.update_spans(prepared.spans, text_width)
            self.speed = notification_reading.pace("".join(span.text for span in prepared.spans), prepared.body_height, self.line_height)
            before, after = notification_text.answer(previous), notification_text.answer(content)
            if (
                before is not None
                and after is not None
                and before.identity == after.identity
                and after.state is not StreamState.INTERRUPTED
                and self.owner.animations()
                and not (self.finish is not None and _contrast(self.finish.preference))
            ):
                end = units("".join(span.text for span in self.spans))
                if end > offset:
                    self.reveals = (*self.reveals[-11:], Reveal(offset, end, self.owner.clock()))
        self.place_content(
            self.frame.width if previous is not None else width,
            self.frame.height if previous is not None else self.height,
            self.frame.details if previous is not None else self.layout.details_height,
        )
        if _recording(content):
            self.tail_pending = True  # Follow the newest transcript after Qt resolves the final viewport.
        self.window.setAccessibleName(f"{heading(content)}. {prepared.caption}".strip())
        self.window.update()

    def fade_text(self, now: float, *, animate: bool) -> bool:
        self.reveals = tuple(reveal for reveal in self.reveals if animate and now - reveal.started < REVEAL_SECONDS)
        # Streamed text materializes into the body's ink from a fainter one.
        body = self.style.text.quiet

        def selection(reveal: Reveal) -> QTextEdit.ExtraSelection:
            amount = max(0.0, min(1.0, (now - reveal.started) / REVEAL_SECONDS))
            value = QTextEdit.ExtraSelection()
            value.cursor = QTextCursor(self.text.document())
            value.cursor.setPosition(min(reveal.start, self.text.document().characterCount() - 1))
            value.cursor.setPosition(min(reveal.end, self.text.document().characterCount() - 1), QTextCursor.MoveMode.KeepAnchor)
            value.format = QTextCharFormat()
            value.format.setForeground(color(Shade(body.color, body.opacity * (0.35 + 0.65 * amount))))
            return value

        self.text.setExtraSelections([selection(reveal) for reveal in self.reveals])
        return bool(self.reveals)

    def place_heading(self, wide: int, header: float, controls: int) -> None:
        """Titles and meta stack beside the badge, centred on it when they are shorter."""
        width = title_width(wide, controls)
        title = title_height(self.label.text(), width, expanded=self.label.expanded)
        meta = _meta_height(self.caption.text()) if not self.caption.isHidden() else 0
        top = TOP + max(0, round((header - TOP - title - meta) / 2))
        self.label.setGeometry(TEXT_LEFT, top, width, max(1, title))
        self.caption.setGeometry(TEXT_LEFT, top + title, width, max(1, meta))

    def place_content(self, width: float, height: float, details: float) -> None:
        if self.layout is None or self.prepared is None:
            return
        scale = self.owner.scale
        layout, prepared = self.layout, self.prepared[2]
        wide = round(width / scale)
        header = prepared.header_height / scale
        # Controls run leftwards from the trailing edge, centred on the badge.
        right, controls = wide - RIGHT, 0
        for button in (self.dismiss, self.stop, self.disclosure):
            if not button.isHidden():
                button.setGeometry(right - CONTROL, TOP + (BADGE - CONTROL) // 2, CONTROL, CONTROL)
                right -= CONTROL + CONTROL_GAP
                controls += 1
        self.badge.move(LEFT, TOP)
        self.place_heading(wide, header, controls)
        detail_height = max(0, min(details, height - prepared.header_height - layout.hint_height - prepared.padding))
        top = prepared.header_height + detail_height
        body_height = max(0, min(layout.body_height, height - top - layout.hint_height - prepared.padding))
        text_width = max(1, wide - TEXT_LEFT - RIGHT)
        for text, start, visible in ((self.details, prepared.header_height, detail_height), (self.text, top, body_height)):
            if visible > SECTION * 2 * scale:
                offset = self.detail_offset if text is self.details and self.expanded else text.offset
                text.setGeometry(TEXT_LEFT, round(start / scale) + SECTION, text_width, max(1, round(visible / scale) - SECTION * 2))
                text.fit_width()
                text.show()
                text.verticalScrollBar().setValue(offset)
            else:
                text.hide()
        self.place_footer(round((top + body_height) / scale), text_width)

    def place_footer(self, top: int, width: int) -> None:
        if self.layout is None or self.prepared is None:
            return
        scale = self.owner.scale
        layout, prepared = self.layout, self.prepared[2]
        footer_top = top
        canvas = len(prepared.canvas_actions) * CANVAS_ROW
        if self.choices:
            self.hint.hide()
            geometry = action_geometry(tuple(button.text() for button in self.choices), width)
            for button, (x, y, button_width) in zip(self.choices, geometry, strict=True):
                button.setGeometry(TEXT_LEFT + x, footer_top + ACTIONS_TOP + y, button_width, ACTION)
                button.show()
            footer_top += ACTIONS_TOP + geometry[-1][1] + ACTION
        elif layout.hint_height > canvas * scale:
            hint_height = round(layout.hint_height / scale) - canvas
            self.hint.setGeometry(TEXT_LEFT, footer_top + SECTION, width, max(1, hint_height - SECTION * 2))
            self.hint.show()
            footer_top += hint_height
        else:
            self.hint.hide()
        for _span, button in self.canvas_actions:
            button.setGeometry(TEXT_LEFT, footer_top + CANVAS_ROW - ACTION, min(width, button.sizeHint().width()), ACTION)
            button.show()
            footer_top += CANVAS_ROW
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
        if self.bounds is None or (self.bounds.width, self.bounds.height) != (bounds.width, bounds.height) or self.frame.details != frame.details:
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
        if not retarget and self.motion is not None and toast_stack.target(self.motion) == end:
            return
        current = toast_stack.advance(self.motion, now) if self.motion is not None else toast_stack.start(self.frame, now)
        moving = toast_stack.retarget(current, end)
        if toast_stack.resting(moving):
            self.motion = None
            self.position(self.right, end)
        else:
            self.motion = moving

    def reveal(self) -> None:
        self.window.show()
        windows.show_quietly(self.handle, visible=True)
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


def _turn(content: Content | None) -> bool:
    match content:
        case Turn():
            return True
        case _:
            return False


def _settled_turn(content: Content) -> bool:
    """A finished turn shows a compact header."""
    match content:
        case Turn(state=Settled()):
            return True
        case _:
            return False


def _recording(content: Content | None) -> bool:
    match content:
        case Recording():
            return True
        case _:
            return False


def _stopping(content: Content) -> bool:
    """Stop is already underway, so its control stays disabled."""
    match content:
        case Turn(state=Working(phase=Busy.STOPPING)):
            return True
        case Recording(state=state):
            return state.phase == "stopping"
        case _:
            return False


def _contrast(preference: appearance.Preference) -> bool:
    match preference:
        case appearance.Contrast():
            return True
        case appearance.Material():
            return False
