"""The card anatomy shared by floating notifications and canvas: surface, app badge, titles and actions.

A card is the kit's `<lg-card>`: a rounded app badge in the app's own colour, a
title row, a meta line and the body beside it, then actions aligned with the
text. Glass cards are functional UI such as the agent feed. The canvas still
uses the earlier bubble surface and circular source badges at the end of this
module until it adopts the card anatomy.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, assert_never

lazy from PySide6.QtCore import QPointF, QRect, QRectF, Qt
lazy from PySide6.QtGui import QColor, QFont, QFontMetricsF, QLinearGradient, QPainter, QPainterPath, QPaintEvent, QPalette, QPen
lazy from PySide6.QtWidgets import QLabel, QWidget

from assistant.feed_origin import App, Origin
from assistant.qt_runtime import prepare
from assistant.ui_components import typeface
from assistant.ui_components.appearance import GLASS_ACCENT, Scheme, Shade, brand, tokens
from assistant.ui_components.text import BODY, META, TextInk, color, contrast_ink, face, text_ink
from assistant.vector_icons import icon
from winapi import appearance

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
ACTION_GAP: Final = 6
ACTIONS_TOP: Final = 12


@dataclass(frozen=True, slots=True)
class Glass:
    """Composition draws the veil; Qt paints the rim light and an invisible hit fill."""

    veil: Shade
    rim: tuple[Shade, Shade, Shade]  # upper-leading, the long middle, the trailing foot


@dataclass(frozen=True, slots=True)
class Solid:
    fill: Shade
    edge: Shade


type Surface = Glass | Solid


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
    surface: Surface
    text: TextInk
    controls: Controls
    thumb: Shade  # overlay scroll bars


def look(preference: appearance.Preference, scheme: Scheme) -> Look:
    """Large glass follows Windows' app scheme; high contrast uses the system colours."""
    match preference:
        case appearance.Contrast(background=background, foreground=foreground):
            ink, ground = Shade(foreground), Shade(background)
            controls = Controls(ink, ground, Shade(foreground, 0.2), Shade(foreground, 0.35), ink, ink, ground, ink)
            return Look(Solid(ground, ink), contrast_ink(foreground, background), controls, ink)
        case appearance.Material.SOLID | appearance.Material.GLASS:
            pass
        case _:
            assert_never(preference)
    theme = tokens(scheme)
    clear = Shade(theme.ink.color, 0)
    controls = Controls(
        theme.ink, theme.hover, theme.press, Shade(theme.ink.color, 0.18), clear, Shade(GLASS_ACCENT), Shade("#ffffff"), Shade(GLASS_ACCENT)
    )
    if preference is appearance.Material.SOLID:
        return Look(Solid(Shade(theme.solid), theme.solid_edge), text_ink(theme), controls, theme.thumb)
    match scheme:
        case Scheme.DARK:
            glass = Glass(Shade("#222226", 0.64), (Shade("#ffffff", 0.55), Shade("#ffffff", 0.06), Shade("#ffffff", 0.22)))
        case Scheme.LIGHT:
            glass = Glass(Shade("#fafafc", 0.66), (Shade("#ffffff", 0.95), Shade("#ffffff", 0.16), Shade("#ffffff", 0.42)))
        case _:
            assert_never(scheme)
    return Look(glass, text_ink(theme), controls, theme.thumb)


def _rim(bounds: QRectF, rim: tuple[Shade, Shade, Shade]) -> QLinearGradient:
    """CSS's 160deg gradient: brightest where light catches the upper-leading curve."""
    angle = math.radians(160)
    dx, dy = math.sin(angle), -math.cos(angle)
    half = (abs(bounds.width() * dx) + abs(bounds.height() * dy)) / 2
    center = bounds.center()
    gradient = QLinearGradient(center - QPointF(dx * half, dy * half), center + QPointF(dx * half, dy * half))
    high, low, end = rim
    for stop, shade in ((0.0, high), (0.34, low), (0.72, low), (1.0, end)):
        gradient.setColorAt(stop, color(shade))
    return gradient


def paint_card(painter: QPainter, bounds: QRectF, surface: Surface) -> None:
    """Qt owns the paint target; glass leaves its veil to composition."""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    edge = bounds.adjusted(0.5, 0.5, -0.5, -0.5)
    outline = QPainterPath()
    outline.addRoundedRect(edge, RADIUS - 0.5, RADIUS - 0.5)
    match surface:
        case Glass(rim=rim):
            # A nearly transparent fill keeps the rounded shape hit-testable.
            painter.fillPath(outline, QColor(1, 1, 1, 1))
            painter.setPen(QPen(_rim(edge, rim), 1))
        case Solid(fill=fill, edge=line):
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


def _app(mark: Mark) -> App:
    match mark:
        case Spinning(app=app):
            return app
        case App():
            return mark
        case _:
            assert_never(mark)


def initial(app: App) -> str:
    """The letter an app's badge shows; taking the whole enum keeps its value typed."""
    return app.value[:1].upper()


def paint_badge(painter: QPainter, bounds: QRectF, mark: Mark) -> None:
    """The kit's app badge: a rounded tile in the app's own colour with a white glyph."""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    tint = QColor(brand(_app(mark)))
    tile = QLinearGradient(bounds.topLeft(), bounds.bottomRight())
    tile.setColorAt(0, tint.lighter(118))
    tile.setColorAt(1, tint)
    painter.setPen(QPen(QColor(255, 255, 255, 77), 0.5))
    painter.setBrush(tile)
    painter.drawRoundedRect(bounds.adjusted(0.25, 0.25, -0.25, -0.25), BADGE_RADIUS, BADGE_RADIUS)
    center = bounds.center()
    match mark:
        case Spinning(angle=angle):
            ring = QRectF(center.x() - 7, center.y() - 7, 14, 14)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(255, 255, 255, 90), 1.8))
            painter.drawEllipse(ring)
            painter.setPen(QPen(QColor("#ffffff"), 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawArc(ring, round(angle * 16), 90 * 16)
        case App.WORKSPACE:
            icon("agent", "#ffffff").paint(painter, QRect(round(center.x()) - 8, round(center.y()) - 8, 16, 16))
        case App():
            painter.setPen(QColor("#ffffff"))
            painter.setFont(face(BODY, 700))
            painter.drawText(bounds, Qt.AlignmentFlag.AlignCenter, initial(mark))
        case _:
            assert_never(mark)
    painter.restore()


def title_face() -> QFont:
    value = face(BODY, 600)
    value.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 99.4)  # the kit's -0.006em
    return value


def meta_face() -> QFont:
    return face(META)


def title_height(text: str, width: int, *, expanded: bool) -> int:
    metrics = QFontMetricsF(title_face())
    if expanded:
        return math.ceil(metrics.boundingRect(QRectF(0, 0, max(1, width), 10000), Qt.TextFlag.TextWordWrap.value, text).height())
    return math.ceil(metrics.height())


def title_text(text: str, width: int, *, expanded: bool) -> str:
    return text if expanded else QFontMetricsF(title_face()).elidedText(text, Qt.TextElideMode.ElideRight, width)


def controls_width(count: int) -> int:
    return count * CONTROL + max(0, count - 1) * CONTROL_GAP


def title_width(width: int, controls: int) -> int:
    """Titles run from the badge to the trailing controls, 6 px clear of them."""
    return max(1, width - TEXT_LEFT - RIGHT - controls_width(controls) - (6 if controls else 0))


def action_face(*, primary: bool) -> QFont:
    return face(BODY, 600 if primary else 500)


def action_geometry(labels: Sequence[str], width: int) -> tuple[tuple[int, int, int], ...]:
    """The kit's actions share one row equally; labels too long for that wrap at their own width."""
    if not labels:
        return ()
    natural = tuple(math.ceil(QFontMetricsF(action_face(primary=not index)).horizontalAdvance(label)) + 24 for index, label in enumerate(labels))
    share = (width - ACTION_GAP * (len(labels) - 1)) // len(labels)
    if max(natural) <= share:
        return tuple((index * (share + ACTION_GAP), 0, share) for index in range(len(labels)))
    x = y = 0
    placed: tuple[tuple[int, int, int], ...] = ()
    for wide in (min(width, each) for each in natural):
        if x and x + wide > width:
            x, y = 0, y + ACTION + ACTION_GAP
        placed = (*placed, (x, y, wide))
        x += wide + ACTION_GAP
    return placed


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
    """A card's title: one elided line, or the whole title while the card is expanded."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        # Qt owns mutable presentation; this flag selects its current paint/layout.
        self.expanded: bool = False
        self.setFont(title_face())

    def display_text(self) -> str:
        return title_text(self.text(), self.width(), expanded=self.expanded)

    def heightForWidth(self, width: int) -> int:
        return title_height(self.text(), width, expanded=self.expanded)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setFont(title_face())
        painter.setPen(self.palette().color(QPalette.ColorRole.WindowText))
        flags = Qt.AlignmentFlag.AlignLeft.value | Qt.AlignmentFlag.AlignVCenter.value
        if self.expanded:
            flags |= Qt.TextFlag.TextWordWrap.value
        painter.drawText(QRectF(self.rect()), flags, self.display_text())
        painter.end()


# The canvas's bubble: its earlier surface, circular source badges and point-sized
# heading, kept with their signatures until the canvas adopts the card anatomy.
TITLE_SIZE = 13.0


def badge_origins(origins: tuple[Origin, ...], app: App = App.WORKSPACE) -> tuple[Origin, ...]:
    """A bubble without explicit sources shows the badge of the app that owns its content."""
    return origins or (Origin(app, app.value),)
