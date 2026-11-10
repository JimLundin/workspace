"""Paints the key hints: a keycap badge inside each window's corner.

The bar owns the hints and hands this overlay its badges. Every badge is a
click-through tool window that never activates. Badge windows are pooled, so
showing hints only moves, repaints and reveals windows. Nothing runs while
they're hidden.
"""

import math
from dataclasses import dataclass, field, replace
from typing import Final, assert_never, override

lazy from PySide6 import QtCore, QtGui, QtWidgets
lazy from PySide6.QtCore import Qt

from cell import Cell
from desktop_ui.components.appearance import (
    GLASS,
    GLASS_ACCENT,
    ON_ACCENT,
    CanvasBar,
    Glass,
    GlassLook,
    Look,
    Rim,
    Scheme,
    Shade,
    SolidLook,
    look,
    rim_stops,
)
from desktop_ui.components.meaning import Tint
from desktop_ui.components.text import color, inter, outline, paint_capsule
from desktop_ui.components.typeface import TYPE
from desktop_ui.components.widgets import tool_window
from desktop_ui.key_hints import ActionCap, AppCap, Badge, DirectionCap, Keycap
from desktop_ui.navigation import Direction
from desktop_ui.overlay_desktop import NativeOverlayDesktop
from desktop_ui.qt_runtime import prepare
from winapi.appearance import Contrast, Material, Preference

prepare()

HEIGHT: Final = 26
"""The bar's 34 px capsule, scaled down to a badge."""
CAP: Final = 20
"""A keycap circle, concentric 3 px inside its badge."""
GAP: Final = 4
CORNER: Final = 8
"""Each badge's inset from its window's top-left corner."""
ARROWS: Final = {Direction.LEFT: "←", Direction.DOWN: "↓", Direction.UP: "↑", Direction.RIGHT: "→"}


def rim_gradient(bounds: QtCore.QRectF, rim: Rim, glass: Glass) -> QtGui.QLinearGradient:
    """The rim's CSS-angled gradient: brightest where light catches the upper-leading curve."""
    angle = math.radians(glass.lighting.rim_angle)
    dx, dy = math.sin(angle), -math.cos(angle)
    half = (abs(bounds.width() * dx) + abs(bounds.height() * dy)) / 2
    center = bounds.center()
    gradient = QtGui.QLinearGradient(center - QtCore.QPointF(dx * half, dy * half), center + QtCore.QPointF(dx * half, dy * half))
    for stop in rim_stops(rim, glass):
        gradient.setColorAt(stop.offset, color(Shade(stop.color, stop.opacity)))
    return gradient


def keycap_text(keycap: Keycap) -> str:
    match keycap:
        case AppCap(letter=letter) | ActionCap(letter=letter):
            return letter
        case DirectionCap(letter=letter, direction=direction):
            return f"{ARROWS[direction]} {letter}"
        case _:
            assert_never(keycap)


@dataclass(frozen=True, slots=True)
class Style:
    """How the hints read in the user's material."""

    surface: Look
    contrast: bool = field(kw_only=True)


@dataclass(frozen=True, slots=True)
class Face:
    """One keycap as painted: its fill, if any, its ink and its text."""

    fill: Shade | None
    ink: Shade
    text: str


def keycap_face(keycap: Keycap, style: Style) -> Face:
    """The app's letter sits in a well and the window its next press reaches takes the accent; actions read quietly."""
    lettering, text = style.surface.lettering, keycap_text(keycap)
    match keycap:
        case AppCap(next=True) if style.contrast:
            # High contrast swaps the system colours instead of adding a hue.
            return Face(lettering.ink, background(style.surface), text)
        case AppCap(next=True):
            return Face(Shade(GLASS_ACCENT), Shade(ON_ACCENT), text)
        case AppCap():
            return Face(lettering.hover, lettering.ink, text)
        case DirectionCap():
            return Face(None, lettering.ink, text)
        case ActionCap():
            return Face(None, lettering.ink if style.contrast else lettering.quiet, text)
        case _:
            assert_never(keycap)


def background(surface: Look) -> Shade:
    match surface:
        case GlassLook(veil=fill) | SolidLook(fill=fill):
            return Shade(fill.color)
        case _:
            assert_never(surface)


def style(preference: Preference, glass: Glass) -> Style:
    """Hints float over any window without composition's blur, so glass takes the thicker Qt-painted veil."""
    surface = look(preference, CanvasBar(Scheme.DARK), Tint.NONE, glass)
    match preference:
        case Contrast():
            return Style(surface, contrast=True)
        case Material.GLASS | Material.SOLID:
            return Style(surface, contrast=False)
        case _:
            assert_never(preference)


def keycap_width(keycap: Keycap, metrics: QtGui.QFontMetricsF) -> float:
    """A circle, widened into a pill with a 6 px inset when its text needs more room."""
    return max(float(CAP), metrics.horizontalAdvance(keycap_text(keycap)) + 12)


def badge_width(keycaps: tuple[Keycap, ...], metrics: QtGui.QFontMetricsF) -> int:
    inner = sum(keycap_width(keycap, metrics) for keycap in keycaps) + GAP * (len(keycaps) - 1)
    return round(inner + (HEIGHT - CAP))


def paint_surface(painter: QtGui.QPainter, bounds: QtCore.QRectF, surface: Look, glass: Glass) -> None:
    """A capsule. Glass without composition: its veil and rim light, painted by Qt; solid and high contrast fill and edge."""
    edge = bounds.adjusted(0.5, 0.5, -0.5, -0.5)
    path = outline(edge, bounds.height() / 2 - 0.5)
    match surface:
        case GlassLook(veil=veil, rim=rim):
            painter.fillPath(path, color(veil))
            painter.setPen(QtGui.QPen(rim_gradient(edge, rim, glass), 1))
            painter.drawPath(path)
        case SolidLook():
            paint_capsule(painter, path, surface)
        case _:
            assert_never(surface)


def paint_keycap(painter: QtGui.QPainter, bounds: QtCore.QRectF, face: Face) -> None:
    if face.fill is not None:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color(face.fill))
        painter.drawRoundedRect(bounds, bounds.height() / 2, bounds.height() / 2)
    painter.setPen(color(face.ink))
    painter.drawText(bounds, Qt.AlignmentFlag.AlignCenter, face.text)


class BadgeWindow(QtWidgets.QWidget):
    """One window's badge: a capsule of keycaps."""

    __slots__ = ("keycaps", "look")

    def __init__(self) -> None:
        super().__init__()
        tool_window(self, "Workspace key hint", on_top=True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.keycaps: tuple[Keycap, ...] = ()
        self.look = style(Material.SOLID, GLASS)

    def draw(self, keycaps: tuple[Keycap, ...], look: Style) -> None:
        self.keycaps, self.look = keycaps, look
        self.resize(badge_width(keycaps, QtGui.QFontMetricsF(inter(TYPE.label))), HEIGHT)
        self.update()

    @override
    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.setFont(inter(TYPE.label))
        paint_surface(painter, QtCore.QRectF(self.rect()), self.look.surface, GLASS)
        metrics = QtGui.QFontMetricsF(inter(TYPE.label))
        left = (HEIGHT - CAP) / 2
        for keycap in self.keycaps:
            width = keycap_width(keycap, metrics)
            paint_keycap(painter, QtCore.QRectF(left, (HEIGHT - CAP) / 2, width, CAP), keycap_face(keycap, self.look))
            left += width + GAP


def logical(x: int, y: int) -> QtCore.QPoint:
    """A physical desktop pixel in Qt's coordinates, which keep each screen's native origin and scale within it."""
    for screen in QtGui.QGuiApplication.screens():
        geometry, ratio = screen.geometry(), screen.devicePixelRatio()
        left, top = geometry.x(), geometry.y()
        if left <= x < left + geometry.width() * ratio and top <= y < top + geometry.height() * ratio:
            return QtCore.QPoint(left + round((x - left) / ratio), top + round((y - top) / ratio))
    return QtCore.QPoint(x, y)


@dataclass(frozen=True, slots=True)
class _Badges:
    badges: tuple[BadgeWindow, ...] = ()
    """Pooled native windows, grown to the most badges shown so far and reused."""
    shown: tuple[tuple[Badge, ...], Preference] | None = None


@dataclass(frozen=True, slots=True)
class KeyHintOverlay:
    """Shows the badges the bar decides; unchanged badges repaint nothing."""

    surface: NativeOverlayDesktop = field(default_factory=NativeOverlayDesktop)
    _state: Cell[_Badges] = field(default_factory=lambda: Cell(_Badges()), init=False, repr=False)

    def _prepared(self) -> BadgeWindow:
        window = BadgeWindow()
        self.surface.prepare(window, click_through=True)
        return window

    def show(self, badges: tuple[Badge, ...], preference: Preference) -> None:
        if self._state.get().shown == (badges, preference):
            return
        pooled = self._state.get().badges
        grown = (*pooled, *(self._prepared() for _ in range(len(badges) - len(pooled))))
        self._state.set(_Badges(grown, (badges, preference)))
        look = style(preference, GLASS)
        for window, badge in zip(grown, badges, strict=False):
            window.draw(badge.keycaps, look)
            window.move(logical(badge.rect.left, badge.rect.top) + QtCore.QPoint(CORNER, CORNER))
            self.surface.present(window)
        for window in grown[len(badges) :]:
            window.hide()

    def close(self) -> None:
        for window in self._state.get().badges:
            window.close()
            window.deleteLater()
        self._state.set(replace(self._state.get(), badges=()))
