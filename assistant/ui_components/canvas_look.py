"""The work canvas's Liquid Glass look, after the kit's window, card, app badge and island bar.

Cards are content, so they are solid; the floating toolbar is the canvas's only
glass. Colour carries meaning only: each app's colour on its badge, orange on a
waiting question, and the accent for selection and relationships. Every surface
reads one scheme's tokens, so the canvas follows Windows' app mode.
"""

from dataclasses import dataclass
from enum import Enum, auto
from functools import lru_cache
from typing import Final, assert_never

lazy from PySide6 import QtCore, QtGui
lazy from PySide6.QtCore import Qt

from assistant.feed_origin import App, Origin
from assistant.qt_runtime import prepare
from assistant.ui_components import text
from assistant.ui_components.appearance import ATTENTION, GLASS_ACCENT, GlassLook, Scheme, Shade, Tokens, brand, rim_stops
from assistant.vector_icons import icon

prepare()

WINDOW_RADIUS: Final = 26
CARD_RADIUS: Final = 18
GROUP_RADIUS: Final = 28
PADDING: Final = 16  # a card's sides; its top is 14 and its foot 15, as the kit's solid card
BADGE: Final = 22  # the kit's small app badge, 7 px corners
BADGE_STEP: Final = 16  # stacked badges overlap, each ringed in its card's surface
CONTROL: Final = 28  # a concentric control inside a 34 px capsule
CAPSULE: Final = 34
# The glass capsule's widget keeps room for its shadow, so painting stays inside Qt's bounds.
SHADOW: Final = QtCore.QMargins(10, 4, 10, 12)


class Role(Enum):
    """Inter at the kit's sizes and weights, tightened as Apple's tracking table does."""

    TITLE = auto()  # a card's title: 14 px semibold
    GROUP = auto()  # an open group's title: 15 px semibold
    META = auto()  # the meta line under a title: 11.5 px
    BODY = auto()  # previews and details: 13 px
    CONTROL = auto()  # control captions and counts: 12 px medium
    BADGE = auto()  # a letter on an app badge: 11 px bold


@lru_cache(maxsize=8)
def face(role: Role) -> QtGui.QFont:
    match role:
        case Role.TITLE:
            size, weight, tracking = 14.0, 600, -0.084
        case Role.GROUP:
            size, weight, tracking = 15.0, 600, -0.15
        case Role.META:
            size, weight, tracking = 11.5, 400, 0.0
        case Role.BODY:
            size, weight, tracking = 13.0, 400, -0.04
        case Role.CONTROL:
            size, weight, tracking = 12.0, 500, 0.0
        case Role.BADGE:
            size, weight, tracking = 11.0, 700, 0.0
        case _:
            assert_never(role)
    value = text.face(size, weight)
    value.setLetterSpacing(QtGui.QFont.SpacingType.AbsoluteSpacing, tracking)
    return value


def mix(tint: str, amount: float, base: str) -> QtGui.QColor:
    """CSS color-mix in sRGB: `amount` of `tint` over an opaque `base`."""
    over, under = QtGui.QColor(tint), QtGui.QColor(base)
    return QtGui.QColor(
        round(over.red() * amount + under.red() * (1 - amount)),
        round(over.green() * amount + under.green() * (1 - amount)),
        round(over.blue() * amount + under.blue() * (1 - amount)),
    )


def flat(shade: Shade, base: str) -> str:
    """A translucent ink flattened over its opaque surface, for symbols drawn as SVG fills."""
    return mix(shade.color, shade.opacity, base).name()


class Surface(Enum):
    CARD = auto()  # solid content
    QUESTION = auto()  # a question waiting for you: the solid card tinted orange
    GROUP = auto()  # an open container: a quiet well around its pieces


def rounded(bounds: QtCore.QRectF, radius: float) -> QtGui.QPainterPath:
    path = QtGui.QPainterPath()
    path.addRoundedRect(bounds, radius, radius)
    return path


def card_shape(bounds: QtCore.QRectF, surface: Surface) -> QtCore.QRectF:
    """Solid cards keep their shadow inside the item, so hit testing and connections use its exact bounds."""
    match surface:
        case Surface.CARD | Surface.QUESTION:
            return bounds.adjusted(0.5, 0.5, -0.5, -2.5)
        case Surface.GROUP:
            return bounds.adjusted(0.5, 0.5, -0.5, -0.5)
        case _:
            assert_never(surface)


def radius(surface: Surface) -> float:
    match surface:
        case Surface.CARD | Surface.QUESTION:
            return CARD_RADIUS
        case Surface.GROUP:
            return GROUP_RADIUS
        case _:
            assert_never(surface)


def surface_fill(theme: Tokens, surface: Surface) -> QtGui.QColor:
    match surface:
        case Surface.CARD:
            return QtGui.QColor(theme.solid)
        case Surface.QUESTION:
            return mix(ATTENTION, 0.14, theme.solid)
        case Surface.GROUP:
            return text.color(Shade(theme.ink.color, 0.04))
        case _:
            assert_never(surface)


def paint_surface(painter: QtGui.QPainter, bounds: QtCore.QRectF, theme: Tokens, surface: Surface) -> None:
    painter.save()
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    shape = card_shape(bounds, surface)
    match surface:
        case Surface.CARD | Surface.QUESTION:
            # The kit's solid shadow, folded into two soft steps beneath the card.
            near, far = (0.30, 0.16) if theme.scheme is Scheme.DARK else (0.07, 0.04)
            painter.fillPath(rounded(shape.translated(0, 2), CARD_RADIUS), QtGui.QColor(0, 0, 0, round(far * 255)))
            painter.fillPath(rounded(shape.translated(0, 1), CARD_RADIUS), QtGui.QColor(0, 0, 0, round(near * 255)))
            edge = text.color(theme.solid_edge) if surface is Surface.CARD else text.color(Shade(ATTENTION, 0.45))
        case Surface.GROUP:
            edge = text.color(Shade(theme.ink.color, 0.07))
        case _:
            assert_never(surface)
    painter.fillPath(rounded(shape, radius(surface)), surface_fill(theme, surface))
    painter.setPen(QtGui.QPen(edge, 1))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPath(rounded(shape, radius(surface)))
    painter.restore()


def paint_selection(painter: QtGui.QPainter, bounds: QtCore.QRectF, surface: Surface, *, drop: bool) -> None:
    """Selection rings the card in the accent; a drop target also takes a faint accent wash."""
    painter.save()
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    shape = card_shape(bounds, surface).adjusted(0.5, 0.5, -0.5, -0.5)
    if drop:
        painter.fillPath(rounded(shape, radius(surface)), text.color(Shade(GLASS_ACCENT, 0.10)))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QtGui.QPen(QtGui.QColor(GLASS_ACCENT), 2))
    painter.drawPath(rounded(shape, radius(surface) - 0.5))
    painter.restore()


@dataclass(frozen=True, slots=True)
class Letter:
    text: str


@dataclass(frozen=True, slots=True)
class Symbol:
    name: str


type Glyph = Letter | Symbol


def glyph(app: App) -> Glyph:
    """Brands read as their initial; Workspace and generic content as a symbol."""
    match app:
        case App.TEAMS:
            return Letter("T")
        case App.OUTLOOK:
            return Letter("O")
        case App.KANBAN:
            return Letter("K")
        case App.CODEX:
            return Letter("X")
        case App.CLAUDE:
            return Letter("C")
        case App.EDGE:
            return Letter("E")
        case App.WINDOWS:
            return Symbol("grid")
        case App.DOCUMENT:
            return Symbol("doc")
        case App.WEB_PAGE:
            return Symbol("globe")
        case App.WORKSPACE:
            return Symbol("agent")
        case _:
            assert_never(app)


def badge_width(origins: tuple[Origin, ...]) -> int:
    return BADGE + BADGE_STEP * (max(1, min(3, len(origins))) - 1)


def paint_badges(painter: QtGui.QPainter, origins: tuple[Origin, ...], at: QtCore.QPointF, ring: QtGui.QColor) -> None:
    """Rounded app badges, the only place an app's colour appears; later badges tuck under earlier ones."""
    painter.save()
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    for index, origin in reversed(tuple(enumerate(origins[:3]))):
        bounds = QtCore.QRectF(at.x() + index * BADGE_STEP, at.y(), BADGE, BADGE)
        if index:
            painter.fillPath(rounded(bounds.adjusted(-2, -2, 2, 2), 9), ring)
        base = QtGui.QColor(brand(origin.app))
        gradient = QtGui.QLinearGradient(bounds.topLeft(), bounds.bottomRight())
        gradient.setColorAt(0, base.lighter(122))
        gradient.setColorAt(1, base)
        painter.fillPath(rounded(bounds, 7), gradient)
        painter.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 76), 0.5))
        painter.drawPath(rounded(bounds.adjusted(0.25, 0.25, -0.25, -0.25), 6.75))
        match glyph(origin.app):
            case Letter(text=text):
                painter.setPen(QtGui.QColor("#ffffff"))
                painter.setFont(face(Role.BADGE))
                painter.drawText(bounds, Qt.AlignmentFlag.AlignCenter, text)
            case Symbol(name=name):
                icon(name, "#ffffff", 14).paint(painter, bounds.adjusted(4, 4, -4, -4).toRect())
    painter.restore()


@dataclass(frozen=True, slots=True)
class CanvasGlass:
    """A canvas paint treatment: shared glass with scheme-owned shadow and hairline."""

    scheme: Scheme
    look: GlassLook


def paint_glass(painter: QtGui.QPainter, bounds: QtCore.QRectF, surface: CanvasGlass) -> None:
    """The canvas toolbar's glass over the canvas: a veil, a rim lit along its upper-leading curve, and a shadow.

    Qt can't blur the scene beneath a child widget cheaply, so the veil is
    thicker than the desktop island's and keeps small text legible over cards.
    """
    painter.save()
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    corner = bounds.height() / 2
    dark = surface.scheme is Scheme.DARK
    for spread, drop, alpha in ((6, 6, 0.10 if dark else 0.05), (2, 2, 0.22 if dark else 0.07)):
        painter.fillPath(
            rounded(bounds.adjusted(-spread, -spread + drop, spread, spread + drop), corner + spread), QtGui.QColor(0, 0, 0, round(alpha * 255))
        )
    painter.fillPath(rounded(bounds, corner), text.color(surface.look.veil))
    painter.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 115 if dark else 26), 0.5))
    painter.drawPath(rounded(bounds.adjusted(-0.25, -0.25, 0.25, 0.25), corner + 0.25))
    gradient = QtGui.QLinearGradient(bounds.topLeft(), bounds.bottomRight())
    for stop in rim_stops(surface.look.rim):
        # The canvas owns this uncached native colour and retains its eight-bit rim alpha.
        shade = text.color(Shade(stop.color))
        shade.setAlpha(round(stop.opacity * 255))
        gradient.setColorAt(stop.offset, shade)
    painter.setPen(QtGui.QPen(QtGui.QBrush(gradient), 1))
    painter.drawPath(rounded(bounds.adjusted(0.5, 0.5, -0.5, -0.5), corner - 0.5))
    painter.restore()


def paint_scroll_edge(painter: QtGui.QPainter, bounds: QtCore.QRectF, theme: Tokens) -> None:
    """A soft edge where content passes beneath the floating toolbar, fading in toward the window's foot."""
    gradient = QtGui.QLinearGradient(bounds.topLeft(), bounds.bottomLeft())
    window = QtGui.QColor(theme.window)
    clear = QtGui.QColor(window)
    clear.setAlpha(0)
    window.setAlpha(round(0.7 * 255))
    gradient.setColorAt(0, clear)
    gradient.setColorAt(0.7, window)
    gradient.setColorAt(1, window)
    painter.fillRect(bounds, gradient)
