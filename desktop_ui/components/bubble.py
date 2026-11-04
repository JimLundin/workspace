"""The card anatomy shared by floating notifications and canvas: surface, app badge, titles and actions.

A card is the kit's `<lg-card>`: a rounded app badge in the app's own colour, a
title row, a meta line and the body beside it, then actions aligned with the
text. Glass cards are functional UI such as the agent feed.
"""

import math
from dataclasses import dataclass
from enum import Enum, auto
from typing import Final, assert_never

lazy from PySide6.QtCore import QPointF, QRect, QRectF, Qt
lazy from PySide6.QtGui import QColor, QFont, QFontMetricsF, QLinearGradient, QPainter, QPainterPath, QPaintEvent, QPalette, QPen
lazy from PySide6.QtWidgets import QLabel, QWidget

from assistant.feed_origin import App
from desktop_ui.components import appearance, typeface
from desktop_ui.components.appearance import GLASS_ACCENT, GlassLook, Rim, Scheme, Shade, SolidLook, brand, rim_stops, tokens
from desktop_ui.components.meaning import Tint
from desktop_ui.components.text import BODY, META, TextInk, color, contrast_ink, face, text_ink
from desktop_ui.qt_runtime import prepare
from desktop_ui.vector_icons import icon
from winapi.appearance import Contrast, Material, Preference

prepare()

# The kit's glass card: 22 px corners and 12/14/12/12 padding around a 30 px badge.
RADIUS: Final = 22
TOP: Final = 12
RIGHT: Final = 14
BOTTOM: Final = 12
LEFT: Final = 12
BADGE: Final = 30
BADGE_RADIUS: Final = 9
TEXT_LEFT: Final = LEFT + BADGE + 10  # body, steps and actions align with the titles
CONTROL: Final = 28  # the kit's control height; icon controls are circles
CONTROL_GAP: Final = 4
ACTION: Final = 28  # capsule actions with 14 px ends


@dataclass(frozen=True, slots=True)
class Controls:
    """Controls inside a card are filled, never glass: glass doesn't sit on glass."""

    ink: Shade
    fill: Shade
    hover: Shade
    press: Shade
    edge: Shade  # transparent except in high contrast
    accent: Shade  # the primary action
    on_accent: Shade
    focus: Shade


@dataclass(frozen=True, slots=True)
class Look:
    surface: appearance.Look
    text: TextInk
    controls: Controls
    thumb: Shade  # overlay scroll bars


def look(preference: Preference, scheme: Scheme) -> Look:
    """Large glass follows Windows' app scheme; high contrast uses the system colours."""
    surface = appearance.look(preference, appearance.Card(scheme), Tint.NONE)
    match preference:
        case Contrast(background=background, foreground=foreground):
            ink, ground = Shade(foreground), Shade(background)
            controls = Controls(ink, ground, Shade(foreground, 0.2), Shade(foreground, 0.35), ink, ink, ground, ink)
            return Look(surface, contrast_ink(foreground, background), controls, ink)
        case Material.SOLID | Material.GLASS:
            pass
        case _:
            assert_never(preference)
    theme = tokens(scheme)
    clear = Shade(theme.ink.color, 0)
    controls = Controls(
        theme.ink, theme.hover, theme.press, Shade(theme.ink.color, 0.18), clear, Shade(GLASS_ACCENT), Shade("#ffffff"), Shade(GLASS_ACCENT)
    )
    return Look(surface, text_ink(theme), controls, theme.thumb)


def rim_gradient(bounds: QRectF, rim: Rim) -> QLinearGradient:
    """CSS's 160deg gradient: brightest where light catches the upper-leading curve."""
    angle = math.radians(160)
    dx, dy = math.sin(angle), -math.cos(angle)
    half = (abs(bounds.width() * dx) + abs(bounds.height() * dy)) / 2
    center = bounds.center()
    gradient = QLinearGradient(center - QPointF(dx * half, dy * half), center + QPointF(dx * half, dy * half))
    for stop in rim_stops(rim):
        gradient.setColorAt(stop.offset, color(Shade(stop.color, stop.opacity)))
    return gradient


def paint_card(painter: QPainter, bounds: QRectF, surface: appearance.Look) -> None:
    """Qt owns the paint target; glass leaves its veil to composition."""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    edge = bounds.adjusted(0.5, 0.5, -0.5, -0.5)
    outline = QPainterPath()
    outline.addRoundedRect(edge, RADIUS - 0.5, RADIUS - 0.5)
    match surface:
        case GlassLook(rim=rim):
            # A nearly transparent fill keeps the rounded shape hit-testable.
            painter.fillPath(outline, QColor(1, 1, 1, 1))
            painter.setPen(QPen(rim_gradient(edge, rim), 1))
        case SolidLook(fill=fill, edge=line):
            painter.fillPath(outline, color(fill))
            painter.setPen(QPen(color(line), 1))
        case _:
            assert_never(surface)
    painter.drawPath(outline)
    painter.restore()


@dataclass(frozen=True, slots=True)
class Spinning:
    """Work in progress turns the spinner in place of the app's glyph."""

    app: App
    angle: float


type Mark = App | Spinning


class BadgeSize(Enum):
    """The kit's card and canvas tile geometry and glyph sizes."""

    CARD = auto()  # 30 px tile, 9 px corners, 16 px symbol, 13 px bold letter
    CANVAS = auto()  # 22 px tile, 7 px corners, 14 px symbol, 11 px bold letter


@dataclass(frozen=True, slots=True)
class Badge:
    mark: Mark
    size: BadgeSize


@dataclass(frozen=True, slots=True)
class Letter:
    text: str


@dataclass(frozen=True, slots=True)
class Symbol:
    name: str


type Glyph = Letter | Symbol


def _app(mark: Mark) -> App:
    match mark:
        case Spinning(app=app):
            return app
        case App():
            return mark
        case _:
            assert_never(mark)


def glyph(app: App) -> Glyph:
    """Brands have distinct letters; Workspace and generic content use symbols."""
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


def _paint_mark(painter: QPainter, bounds: QRectF, badge: Badge) -> None:
    """The badge owner's glyph or spinner over its already-painted tile."""
    match badge.size:
        case BadgeSize.CARD:
            symbol_size, letter_size = 16, BODY
        case BadgeSize.CANVAS:
            symbol_size, letter_size = 14, 11.0
        case _:
            assert_never(badge.size)
    center = bounds.center()
    match badge.mark:
        case Spinning(angle=angle):
            ring = QRectF(center.x() - 7, center.y() - 7, 14, 14)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(255, 255, 255, 90), 1.8))
            painter.drawEllipse(ring)
            painter.setPen(QPen(QColor("#ffffff"), 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawArc(ring, round(angle * 16), 90 * 16)
        case App() as app:
            value = glyph(app)
            match value:
                case Letter(text=letter):
                    painter.setPen(QColor("#ffffff"))
                    painter.setFont(face(letter_size, 700))
                    painter.drawText(bounds, Qt.AlignmentFlag.AlignCenter, letter)
                case Symbol(name=name):
                    match badge.size:
                        case BadgeSize.CARD:
                            symbol_bounds = QRect(round(center.x()) - 8, round(center.y()) - 8, symbol_size, symbol_size)
                        case BadgeSize.CANVAS:
                            symbol_bounds = bounds.adjusted(4, 4, -4, -4).toRect()
                        case _:
                            assert_never(badge.size)
                    icon(name, "#ffffff", symbol_size).paint(painter, symbol_bounds)
                case _:
                    assert_never(value)
        case _:
            assert_never(badge.mark)


def paint_badge(painter: QPainter, at: QPointF, badge: Badge) -> None:
    """The kit's app badge: a rounded tile in the app's own colour with a white glyph."""
    match badge.size:
        case BadgeSize.CARD:
            side = BADGE
        case BadgeSize.CANVAS:
            side = 22
        case _:
            assert_never(badge.size)
    bounds = QRectF(at.x(), at.y(), side, side)
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    tint = QColor(brand(_app(badge.mark)))
    tile = QLinearGradient(bounds.topLeft(), bounds.bottomRight())
    tile.setColorAt(0, tint.lighter(118))
    tile.setColorAt(1, tint)
    # Each size retains its existing subpixel fill and border geometry.
    match badge.size:
        case BadgeSize.CARD:
            painter.setPen(QPen(QColor(255, 255, 255, 77), 0.5))
            painter.setBrush(tile)
            painter.drawRoundedRect(bounds.adjusted(0.25, 0.25, -0.25, -0.25), BADGE_RADIUS, BADGE_RADIUS)
        case BadgeSize.CANVAS:
            fill = QPainterPath()
            fill.addRoundedRect(bounds, 7, 7)
            painter.fillPath(fill, tile)
            edge = QPainterPath()
            edge.addRoundedRect(bounds.adjusted(0.25, 0.25, -0.25, -0.25), 6.75, 6.75)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(255, 255, 255, 76), 0.5))
            painter.drawPath(edge)
        case _:
            assert_never(badge.size)
    _paint_mark(painter, bounds, badge)
    painter.restore()


def title_face() -> QFont:
    value = face(BODY, 600)
    value.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 99.4)  # the kit's -0.006em
    return value


def meta_face() -> QFont:
    return face(META)


def title_height() -> int:
    """Card headings keep one line independently of step disclosure."""
    return math.ceil(QFontMetricsF(title_face()).height())


def title_text(text: str, width: int) -> str:
    return QFontMetricsF(title_face()).elidedText(" ".join(text.split()), Qt.TextElideMode.ElideRight, width)


def controls_width(count: int) -> int:
    return count * CONTROL + max(0, count - 1) * CONTROL_GAP


def title_width(width: int, controls: int) -> int:
    """Titles run from the badge to the trailing controls, 6 px clear of them."""
    return max(1, width - TEXT_LEFT - RIGHT - controls_width(controls) - (6 if controls else 0))


def action_face(*, primary: bool) -> QFont:
    return face(BODY, 600 if primary else 500)


def action_style(controls: Controls, *, primary: bool) -> str:
    """A filled or accent capsule for a QPushButton inside a card."""
    fill, ink = (controls.accent, controls.on_accent) if primary else (controls.fill, controls.ink)
    hover = Shade(fill.color, fill.opacity * 0.86) if primary else controls.hover
    press = fill if primary else controls.press
    return (
        f"QPushButton {{ color: {ink.css}; background: {fill.css}; border: 1px solid {controls.edge.css};"
        f" border-radius: {ACTION // 2}px; padding: 0 11px; font-family: '{typeface.FAMILY}'; font-size: {BODY:g}px;"
        f" font-weight: {600 if primary else 500}; }}"
        f" QPushButton:hover {{ background: {hover.css}; }}"
        f" QPushButton:pressed {{ background: {press.css}; }}"
        f" QPushButton:focus {{ outline: none; border: 2px solid {controls.focus.css}; }}"
        f" QPushButton:disabled {{ color: {Shade(ink.color, ink.opacity * 0.45).css}; }}"
    )


class FeedTitle(QLabel):
    """A card's title stays on one elided line; its original text remains accessible."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setFont(title_face())

    def display_text(self) -> str:
        return title_text(self.text(), self.width())

    def heightForWidth(self, width: int) -> int:
        return title_height()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setFont(title_face())
        painter.setPen(self.palette().color(QPalette.ColorRole.WindowText))
        flags = Qt.AlignmentFlag.AlignLeft.value | Qt.AlignmentFlag.AlignVCenter.value
        painter.drawText(QRectF(self.rect()), flags, self.display_text())
        painter.end()
