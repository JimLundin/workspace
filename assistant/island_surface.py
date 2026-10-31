"""The island bar's Qt surface: one screen-wide window, a widget per capsule, and glass behind them.

The window is transparent except where capsules paint, so Windows' per-pixel
hit-testing passes every other click through to the desktop. Each capsule is a
real button, so it keeps its accessible name, tooltip and keyboard focus; each
control inside it is a button of its own. Under glass, composition draws the
veil in one scene behind the window and Qt paints only content over an
invisible (alpha 1) hit fill; without glass, Qt paints the capsule itself.
"""

import math
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import lru_cache
from typing import Final, assert_never

lazy from PySide6 import QtCore, QtGui, QtWidgets
lazy from PySide6.QtCore import Qt

from assistant.island_layout import HEIGHT, WAVE_BARS, Content, Framed, Spot, arrange
from assistant.island_model import Action, Badge, CapsuleView, Control, Glyph, Key, Marker, Spinner, Text, Tint, Tone
from assistant.qt_runtime import prepare
from assistant.qt_ui import EventLoop
from assistant.ui_components import typeface
from assistant.ui_components.appearance import RED, GlassLook, Look, Shade, SolidLook, look, reading
from assistant.vector_icons import icon
from assistant.view_publication import log_view
from components import BAR_WINDOW
from winapi import appearance, windows
from winapi.composition import GlassScene, borderless
from winapi.shapes import Pane, Rect

prepare()

TOP: Final = 8  # The island floats this far below the screen edge.
RADIUS: Final = 17
SHADOW: Final = 40  # Room below and beside the capsules for their composed shadow.


def color(shade: Shade) -> QtGui.QColor:
    value = QtGui.QColor(shade.color)
    value.setAlphaF(shade.opacity)
    return value


@dataclass(frozen=True, slots=True)
class Drawn:
    """One capsule's frame: its view and content, any content fading out under it, and how it reads."""

    view: CapsuleView
    content: Content
    previous: Content | None
    fade: float
    look: Look
    framed: Framed


def visibility(presence: float) -> float:
    """Glass and content become opaque before a capsule reaches its full width."""
    return min(1.0, max(0.0, presence * 1.6))


def controls(content: Content) -> tuple[tuple[Control, float], ...]:
    """The controls a capsule shows, with their left edges."""

    def control(spot: Spot) -> tuple[tuple[Control, float], ...]:
        match spot.part:
            case Control() as part:
                return ((part, spot.x),)
            case _:
                return ()

    return tuple(found for spot in content.spots for found in control(spot))


def pane(key: Key, look: Look, framed: Framed, scale: float) -> Pane | None:
    match look:
        case GlassLook(veil=veil):
            box = framed.box
            bounds = Rect(round(box.x * scale), round(box.y * scale), round((box.x + box.width) * scale), round((box.y + box.height) * scale))
            return Pane(key.name, bounds, RADIUS * scale, visibility(framed.presence), veil)
        case SolidLook():
            return None
        case _:
            assert_never(look)


@lru_cache(maxsize=2)
def font(*, strong: bool) -> QtGui.QFont:
    value = QtGui.QFont(typeface.FAMILY)
    value.setPixelSize(12)
    value.setWeight(QtGui.QFont.Weight.DemiBold if strong else QtGui.QFont.Weight.Medium)
    value.setFeature(QtGui.QFont.Tag("tnum"), 1)  # Readings keep their width as digits change.
    return value


@lru_cache(maxsize=2)
def badge_font() -> QtGui.QFont:
    value = QtGui.QFont(typeface.FAMILY)
    value.setPixelSize(10)
    value.setWeight(QtGui.QFont.Weight.Bold)
    return value


class ControlButton(QtWidgets.QAbstractButton):
    """A concentric 28 px circle inside its capsule, revealed while the pointer is over it."""

    def __init__(self, capsule: Capsule, control: Control) -> None:
        super().__init__(capsule)
        self.capsule = capsule
        self.control = control
        self.setFixedSize(28, 28)
        self.setToolTip(control.label)
        self.setAccessibleName(control.label)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.clicked.connect(self.pressed_control)

    def pressed_control(self) -> None:
        self.capsule.press(self.control.action)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        lettering = self.capsule.look.lettering
        if self.isDown() or self.underMouse():
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color(lettering.press if self.isDown() else lettering.hover))
            painter.drawEllipse(QtCore.QRectF(self.rect()))
        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QtGui.QPen(color(lettering.ink), 1.5))
            painter.drawEllipse(QtCore.QRectF(self.rect()).adjusted(1, 1, -1, -1))
        ink = lettering.ink
        painter.setOpacity(ink.opacity)
        icon(self.control.icon, ink.color).paint(painter, QtCore.QRect(6, 6, 16, 16))


class Capsule(QtWidgets.QAbstractButton):
    """One capsule: its strip to the screen edge, its shape, and its parts.

    A press acts on what the capsule shows; the bar's owner decides what that is.
    """

    def __init__(self, window: BarWindow, key: Key) -> None:
        super().__init__(window)
        self.window_ = window
        self.key = key
        self.view: CapsuleView | None = None
        self.content = Content(HEIGHT, ())
        self.previous: Content | None = None
        self.fade = 1.0
        self.presence = 1.0
        self.look: Look = window.look
        self.contrast = False
        self.controls: tuple[ControlButton, ...] = ()
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.clicked.connect(self.pressed_capsule)

    def press(self, action: Action) -> None:
        self.window_.press(action)

    def pressed_capsule(self) -> None:
        if self.view is not None:
            self.press(self.view.action)

    def show_view(self, drawn: Drawn, *, contrast: bool) -> None:
        state = (drawn.view, drawn.content, drawn.previous, drawn.fade, drawn.look, drawn.framed.presence, contrast)
        if (self.view, self.content, self.previous, self.fade, self.look, self.presence, self.contrast) == state:
            return
        if self.view is None or self.view.label != drawn.view.label:
            # Each change raises an accessibility event; frames of a fade keep the label.
            self.setToolTip(drawn.view.label)
            self.setAccessibleName(drawn.view.label)
        self.view, self.content, self.previous, self.fade, self.look, self.presence, self.contrast = state
        wanted = controls(drawn.content)
        if tuple(button.control for button in self.controls) != tuple(control for control, _ in wanted):
            for button in self.controls:
                # Deletion waits for the event loop; the replaced control must leave this frame.
                button.hide()
                button.deleteLater()
            self.controls = tuple(ControlButton(self, control) for control, _ in wanted)
        self.update()

    def place_controls(self) -> None:
        shift = self.shift(self.content)
        for button, (_, x) in zip(self.controls, controls(self.content), strict=True):
            button.move(round(shift + x), TOP + (HEIGHT - 28) // 2)
            button.setVisible(self.fade > 0.5 and visibility(self.presence) == 1)

    def shift(self, content: Content) -> float:
        """Content keeps its measured layout, centred while the capsule's width morphs around it."""
        return (self.width() - content.width) / 2

    def frame(self, framed: Framed) -> None:
        """The widget spans the edge strip and the capsule below it."""
        self.setGeometry(round(framed.box.x), 0, max(1, round(framed.box.width)), TOP + round(framed.box.height))
        self.place_controls()

    def enterEvent(self, event: QtGui.QEnterEvent) -> None:
        super().enterEvent(event)
        self.window_.hover(self.key)
        self.update()

    def leaveEvent(self, event: QtCore.QEvent) -> None:
        super().leaveEvent(event)
        self.window_.hover(None)
        self.update()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        shape = QtCore.QRectF(0, TOP, self.width(), self.height() - TOP)
        radius = min(RADIUS, shape.height() / 2)
        outline = QtGui.QPainterPath()
        outline.addRoundedRect(shape, radius, radius)
        strip = QtGui.QPainterPath()
        strip.addRect(QtCore.QRectF(0, 0, self.width(), TOP))
        hit = QtGui.QColor(0, 0, 0, 1)  # Invisible, but Windows routes the pointer here.
        painter.fillPath(strip, hit)
        alpha = visibility(self.presence)
        match self.look:
            case GlassLook():
                painter.fillPath(outline, hit)
            case SolidLook(fill=fill, edge=edge):
                painter.setOpacity(alpha)
                painter.fillPath(outline, color(fill))
                painter.setPen(QtGui.QPen(color(edge), 1))
                painter.drawPath(outline)
                painter.setOpacity(1)
            case _:
                assert_never(self.look)
        lettering = self.look.lettering
        if self.isDown() or self.underMouse():
            painter.fillPath(outline, color(lettering.press if self.isDown() else lettering.hover))
        if self.hasFocus():
            painter.setPen(QtGui.QPen(color(lettering.ink), 1.5))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(shape.adjusted(1.5, 1.5, -1.5, -1.5), radius - 1.5, radius - 1.5)
        painter.setClipPath(outline)
        layers: tuple[tuple[Content, float], ...] = (
            ((self.previous, alpha * (1 - self.fade)), (self.content, alpha * self.fade)) if self.previous is not None else ((self.content, alpha),)
        )
        for content, opacity in layers:
            if opacity <= 0:
                continue
            painter.save()
            painter.setOpacity(opacity)
            painter.translate(self.shift(content), 0)
            previous: Spot | None = None
            for spot in content.spots:
                self.paint_part(painter, spot, previous, TOP + HEIGHT / 2)
                previous = spot
            painter.restore()

    def paint_part(self, painter: QtGui.QPainter, spot: Spot, previous: Spot | None, middle: float) -> None:
        lettering = self.look.lettering
        match spot.part:
            case Text(text=text, tone=tone, strong=strong):
                painter.setFont(font(strong=strong))
                painter.setPen(color(reading(lettering, tone, contrast=self.contrast)))
                painter.drawText(QtCore.QRectF(spot.x, TOP, spot.width + 1, HEIGHT), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)
            case Glyph(name=name, tone=tone):
                ink = reading(lettering, tone, contrast=self.contrast)
                painter.save()
                painter.setOpacity(ink.opacity)
                icon(name, ink.color).paint(painter, QtCore.QRect(round(spot.x), round(middle - 8), 16, 16))
                painter.restore()
            case Spinner():
                self.paint_spinner(painter, spot, middle)
            case Badge(text=text):
                anchor = previous.x + previous.width if previous is not None else spot.x
                badge = badge_font()
                width = max(15.0, QtGui.QFontMetricsF(badge).horizontalAdvance(text) + 8)
                rect = QtCore.QRectF(min(anchor - 7, self.content.width - width - 1), TOP + 1, width, 15)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QtGui.QColor(RED) if not self.contrast else color(lettering.ink))
                painter.drawRoundedRect(rect, 7.5, 7.5)
                painter.setFont(badge)
                painter.setPen(QtGui.QColor("#ffffff") if not self.contrast else color(lettering.press))
                painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
            case Control():
                pass  # A child button paints it.
            case Marker.WAVE:
                ink = color(reading(lettering, Tone.INK, contrast=self.contrast))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(ink)
                for index, sample in enumerate(self.window_.samples):
                    height = 3 + sample * 13
                    painter.drawRoundedRect(QtCore.QRectF(spot.x + index * 4, middle - height / 2, 2, height), 1, 1)
            case Marker.DOT:
                red = QtGui.QColor(RED) if not self.contrast else color(lettering.ink)
                halo = QtGui.QColor(red)
                halo.setAlphaF(0.25)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(halo)
                painter.drawEllipse(QtCore.QPointF(spot.x + 4, middle), 7, 7)
                painter.setBrush(red)
                painter.drawEllipse(QtCore.QPointF(spot.x + 4, middle), 4, 4)
            case _:
                assert_never(spot.part)

    def paint_spinner(self, painter: QtGui.QPainter, spot: Spot, middle: float) -> None:
        lettering = self.look.lettering
        ring = QtCore.QRectF(spot.x + 0.9, middle - 6.1, 12.2, 12.2)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QtGui.QPen(color(Shade(lettering.ink.color, 0.3)), 1.8))
        painter.drawEllipse(ring)
        painter.setPen(QtGui.QPen(color(lettering.ink), 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawArc(ring, round(self.window_.spin_angle * 16), 90 * 16)


class BarWindow(QtWidgets.QWidget):
    """The bar's one window: the full width of the primary screen, as tall as the capsules."""

    def __init__(self, loop: EventLoop, press: Callable[[Action], None], hover: Callable[[Key | None], None]) -> None:
        super().__init__()
        self.loop = loop
        self.press = press
        self.hover = hover
        self.look: Look = look(appearance.Material.SOLID, appearance.Frost.SMOKED, Tint.NONE)
        self.capsules: Mapping[Key, Capsule] = frozendict()
        self.spin_angle = 90.0
        # Qt owns the painted trace; samples arrive from the bar's audio meter.
        self.samples: deque[float] = deque([0.0] * WAVE_BARS, maxlen=WAVE_BARS)
        self.scene: GlassScene | None = None
        self.panes: tuple[Pane, ...] = ()
        self.glass = False
        self.setWindowTitle(BAR_WINDOW)
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        borderless(int(self.winId()))
        # Several changes in one Qt turn publish one final glass frame.
        self.glass_timer = QtCore.QTimer(self)
        self.glass_timer.setSingleShot(True)
        self.glass_timer.timeout.connect(self.publish_glass)

    def measure(self, view: CapsuleView) -> Content:
        def width(text: Text) -> float:
            return math.ceil(QtGui.QFontMetricsF(font(strong=text.strong)).horizontalAdvance(text.text))

        return arrange(view.slots, width)

    def capsule(self, key: Key) -> Capsule:
        existing = self.capsules.get(key)
        if existing is not None:
            return existing
        created = Capsule(self, key)
        self.capsules = frozendict({**self.capsules, key: created})
        return created

    def present(self, drawn: tuple[Drawn, ...], *, contrast: bool, glass: bool) -> None:
        """Show exactly these capsules where their frames put them; other pooled capsules hide."""
        area = QtGui.QGuiApplication.primaryScreen().geometry()
        height = TOP + max((round(each.framed.box.height) for each in drawn), default=HEIGHT)
        if self.geometry() != QtCore.QRect(area.x(), area.y(), area.width(), height):
            self.setGeometry(area.x(), area.y(), area.width(), height)
        keys = frozenset(each.view.key for each in drawn)
        for each in drawn:
            capsule = self.capsule(each.view.key)
            capsule.show_view(each, contrast=contrast)
            capsule.frame(each.framed)
            capsule.show()
        for key, capsule in self.capsules.items():
            if key not in keys:
                capsule.hide()
        scale = self.devicePixelRatioF()
        self.glass = glass
        self.panes = tuple(found for each in drawn if (found := pane(each.view.key, each.look, each.framed, scale)) is not None)
        if not self.glass_timer.isActive():
            self.glass_timer.start(0)

    def bounds(self, key: Key) -> Rect | None:
        """A shown capsule's screen rectangle in device pixels. Capsules stay alien widgets:
        a native child window would break the bar's per-pixel hit-testing."""
        capsule = self.capsules.get(key)
        if capsule is None or not capsule.isVisible() or not self.isVisible():
            return None
        outer, scale, shape = windows.outer_rect(int(self.winId())), self.devicePixelRatioF(), capsule.geometry()
        left, top = outer.left + round(shape.x() * scale), outer.top + round((shape.y() + TOP) * scale)
        return Rect(left, top, left + round(shape.width() * scale), top + round((shape.height() - TOP) * scale))

    def publish_glass(self) -> None:
        if not self.isVisible() or not self.glass:
            if self.scene is not None:
                self.scene.hide()
            return
        if self.scene is None and self.loop.composition is not None:
            try:
                self.scene = self.loop.composition.scene("Workspace · Island glass")
            except OSError as error:
                log_view(f"Island glass unavailable; using the solid material: {error}")
        if self.scene is None:
            return
        outer = windows.outer_rect(int(self.winId()))
        margin = round(SHADOW * self.devicePixelRatioF())
        self.scene.place(Rect(outer.left - margin, outer.top, outer.right + margin, outer.bottom + margin), self.devicePixelRatioF())
        self.scene.publish(tuple(Pane(pane.key, shifted(pane.bounds, margin), pane.radius, pane.opacity, pane.veil) for pane in self.panes))
        self.scene.show(int(self.winId()))

    def dispose(self) -> None:
        self.glass_timer.stop()
        self.hide()
        if self.scene is not None:
            self.scene.close()
            self.scene = None
        self.deleteLater()


def shifted(bounds: Rect, margin: int) -> Rect:
    return Rect(bounds.left + margin, bounds.top, bounds.right + margin, bounds.bottom)
