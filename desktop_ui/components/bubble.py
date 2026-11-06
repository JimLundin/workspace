"""The pieces canvas cards share: filled controls, the rim light and the app badge.

A badge is the kit's rounded tile in the app's own colour with a white glyph.
Controls inside a card are filled, never glass: glass doesn't sit on glass.
"""

import math
from dataclasses import dataclass
from typing import Final, assert_never

lazy from PySide6.QtCore import QPointF, QRectF, Qt
lazy from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen

from contracts.feed_origin import App
from desktop_ui.components import typeface
from desktop_ui.components.appearance import Rim, Shade, brand, rim_stops
from desktop_ui.components.text import color, face
from desktop_ui.qt_runtime import prepare
from desktop_ui.vector_icons import icon

prepare()

BODY: Final = 13.0  # pixels, as the kit's body text
BADGE: Final = 22
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


@dataclass(frozen=True, slots=True)
class Letter:
    text: str


@dataclass(frozen=True, slots=True)
class Symbol:
    name: str


type Glyph = Letter | Symbol


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


def paint_badge(painter: QPainter, at: QPointF, app: App) -> None:
    """A 22 px tile with 7 px corners, a 14 px symbol or an 11 px bold letter."""
    bounds = QRectF(at.x(), at.y(), BADGE, BADGE)
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    tint = QColor(brand(app))
    tile = QLinearGradient(bounds.topLeft(), bounds.bottomRight())
    tile.setColorAt(0, tint.lighter(118))
    tile.setColorAt(1, tint)
    fill = QPainterPath()
    fill.addRoundedRect(bounds, 7, 7)
    painter.fillPath(fill, tile)
    edge = QPainterPath()
    edge.addRoundedRect(bounds.adjusted(0.25, 0.25, -0.25, -0.25), 6.75, 6.75)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(QColor(255, 255, 255, 76), 0.5))
    painter.drawPath(edge)
    value = glyph(app)
    match value:
        case Letter(text=letter):
            painter.setPen(QColor("#ffffff"))
            painter.setFont(face(11.0, 700))
            painter.drawText(bounds, Qt.AlignmentFlag.AlignCenter, letter)
        case Symbol(name=name):
            icon(name, "#ffffff", 14).paint(painter, bounds.adjusted(4, 4, -4, -4).toRect())
        case _:
            assert_never(value)
    painter.restore()


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
