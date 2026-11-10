"""Paints the key hints: a keycap badge inside each window's corner.

The bar owns the hints and hands this overlay its badges. Every badge is a
click-through tool window that never activates. Badge windows are pooled, so
showing hints only moves, repaints and reveals windows. Nothing runs while
they're hidden.
"""

import math
from dataclasses import dataclass, field, replace
from typing import assert_never, override

lazy from PySide6 import QtCore, QtGui, QtWidgets
lazy from PySide6.QtCore import Qt

from cell import Cell
from desktop_ui.components.appearance import (
    CanvasBar,
    Glass,
    GlassLook,
    Look,
    Palette,
    Rim,
    Scheme,
    Shade,
    SolidLook,
    look,
    rim_stops,
)
from desktop_ui.components.meaning import Tint
from desktop_ui.components.text import color, inter, outline, paint_capsule
from desktop_ui.components.typeface import Font
from desktop_ui.components.widgets import tool_window
from desktop_ui.key_hints import ActionCap, AppCap, Badge, DirectionCap, Keycap
from desktop_ui.navigation import Direction
from desktop_ui.overlay_desktop import NativeOverlayDesktop
from desktop_ui.qt_runtime import prepare
from winapi.appearance import Contrast, Material, Preference

prepare()


@dataclass(frozen=True, slots=True, kw_only=True)
class BadgeSpec:
    """What a key-hint badge is made of."""

    height: float
    """The bar's capsule, scaled down to a badge."""
    cap: float
    """A keycap circle, concentric inside its badge."""
    gap: float
    """Between keycaps."""
    pad: float
    """A keycap's text inset, when its text widens the circle into a pill."""
    corner: int
    """Each badge's inset from its window's top-left corner."""
    font: Font
    arrows: frozendict[Direction, str]
    """The symbol before a focus chord's letter."""
    scheme: Scheme
    """Badges float over any window, so they keep one scheme."""
    glass: Glass
    palette: Palette
    """The accent marks the window a chord's next press reaches."""


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


def keycap_text(keycap: Keycap, arrows: frozendict[Direction, str]) -> str:
    match keycap:
        case AppCap(letter=letter) | ActionCap(letter=letter):
            return letter
        case DirectionCap(letter=letter, direction=direction):
            return f"{arrows[direction]} {letter}"
        case _:
            assert_never(keycap)


@dataclass(frozen=True, slots=True)
class Style:
    """How the hints read in the user's material."""

    surface: Look
    arrows: frozendict[Direction, str]
    palette: Palette
    contrast: bool = field(kw_only=True)


@dataclass(frozen=True, slots=True)
class Face:
    """One keycap as painted: its fill, if any, its ink and its text."""

    fill: Shade | None
    ink: Shade
    text: str


def keycap_face(keycap: Keycap, style: Style) -> Face:
    """The app's letter sits in a well and the window its next press reaches takes the accent; actions read quietly."""
    lettering, text = style.surface.lettering, keycap_text(keycap, style.arrows)
    match keycap:
        case AppCap(next=True) if style.contrast:
            # High contrast swaps the system colours instead of adding a hue.
            return Face(lettering.ink, background(style.surface), text)
        case AppCap(next=True):
            return Face(Shade(style.palette.accent), Shade(style.palette.on_accent), text)
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


def style(preference: Preference, spec: BadgeSpec) -> Style:
    """Hints float over any window without composition's blur, so glass takes the thicker Qt-painted veil."""
    surface = look(preference, CanvasBar(spec.scheme), Tint.NONE, spec.glass)
    match preference:
        case Contrast():
            return Style(surface, spec.arrows, spec.palette, contrast=True)
        case Material.GLASS | Material.SOLID:
            return Style(surface, spec.arrows, spec.palette, contrast=False)
        case _:
            assert_never(preference)


def keycap_width(keycap: Keycap, metrics: QtGui.QFontMetricsF, spec: BadgeSpec) -> float:
    """A circle, widened into a pill with its text inset when the text needs more room."""
    return max(spec.cap, metrics.horizontalAdvance(keycap_text(keycap, spec.arrows)) + 2 * spec.pad)


def badge_width(keycaps: tuple[Keycap, ...], metrics: QtGui.QFontMetricsF, spec: BadgeSpec) -> int:
    inner = sum(keycap_width(keycap, metrics, spec) for keycap in keycaps) + spec.gap * (len(keycaps) - 1)
    return round(inner + (spec.height - spec.cap))


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

    __slots__ = ("keycaps", "look", "spec")

    def __init__(self, spec: BadgeSpec) -> None:
        super().__init__()
        tool_window(self, "Workspace key hint", on_top=True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.spec = spec
        self.keycaps: tuple[Keycap, ...] = ()
        self.look = style(Material.SOLID, spec)

    def draw(self, keycaps: tuple[Keycap, ...], look: Style) -> None:
        self.keycaps, self.look = keycaps, look
        self.resize(badge_width(keycaps, QtGui.QFontMetricsF(inter(self.spec.font)), self.spec), round(self.spec.height))
        self.update()

    @override
    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        spec = self.spec
        painter.setFont(inter(spec.font))
        paint_surface(painter, QtCore.QRectF(self.rect()), self.look.surface, spec.glass)
        metrics = QtGui.QFontMetricsF(inter(spec.font))
        left = inset = (spec.height - spec.cap) / 2
        for keycap in self.keycaps:
            width = keycap_width(keycap, metrics, spec)
            paint_keycap(painter, QtCore.QRectF(left, inset, width, spec.cap), keycap_face(keycap, self.look))
            left += width + spec.gap


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

    spec: BadgeSpec
    surface: NativeOverlayDesktop = field(default_factory=NativeOverlayDesktop)
    _state: Cell[_Badges] = field(default_factory=lambda: Cell(_Badges()), init=False, repr=False)

    def _prepared(self) -> BadgeWindow:
        window = BadgeWindow(self.spec)
        self.surface.prepare(window, click_through=True)
        return window

    def show(self, badges: tuple[Badge, ...], preference: Preference) -> None:
        if self._state.get().shown == (badges, preference):
            return
        pooled = self._state.get().badges
        grown = (*pooled, *(self._prepared() for _ in range(len(badges) - len(pooled))))
        self._state.set(_Badges(grown, (badges, preference)))
        look = style(preference, self.spec)
        for window, badge in zip(grown, badges, strict=False):
            window.draw(badge.keycaps, look)
            window.move(logical(badge.rect.left, badge.rect.top) + QtCore.QPoint(self.spec.corner, self.spec.corner))
            self.surface.present(window)
        for window in grown[len(badges) :]:
            window.hide()

    def close(self) -> None:
        for window in self._state.get().badges:
            window.close()
            window.deleteLater()
        self._state.set(replace(self._state.get(), badges=()))
