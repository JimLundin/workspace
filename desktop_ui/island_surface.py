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
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field, replace
from functools import lru_cache
from typing import assert_never, override

lazy from PySide6 import QtCore, QtGui, QtWidgets
lazy from PySide6.QtCore import Qt

from components import BAR_WINDOW
from desktop_ui import island_menu
from desktop_ui.bar_control import KeyboardFocus, font, paint_feedback
from desktop_ui.bar_events import Deactivated, Event, Hovered, MenuKey, Picked, Pressed, Selected, TrayClicked, VolumeSet
from desktop_ui.components import appearance
from desktop_ui.components.appearance import GLASS_ACCENT, RED, GlassLook, Look, Shade, SolidLook, reading, rim_stops
from desktop_ui.components.meaning import Tone
from desktop_ui.components.text import color, hit, inter, outline, paint_capsule
from desktop_ui.components.widgets import tool_window
from desktop_ui.island_layout import SIZES, Box, Content, Framed, Spot, Tile, arrange, on_pixels, tiles
from desktop_ui.island_menu import Face, Item, Live, Menu, Slider, Toggle, TrayIcon
from desktop_ui.island_model import Action, CapsuleView, Control, Glyph, Key, Marker, Part, Text
from desktop_ui.qt_runtime import prepare
from desktop_ui.shell_surface import Pager, pixmap
from desktop_ui.vector_icons import paint_icon
from desktop_ui.view_publication import log
from winapi import windows
from winapi.appearance import Frost
from winapi.composition import DesktopComposition, GlassScene, borderless
from winapi.shapes import Pane, Rect, Veil
from winapi.tray_host import Click, Entry, Located

prepare()


@dataclass(frozen=True, slots=True)
class Drawn:
    """One capsule's frame: its view and content, any content fading out under it, and how it reads."""

    view: CapsuleView
    content: Content
    previous: Content | None
    fade: float
    look: Look
    framed: Framed


@dataclass(frozen=True, slots=True)
class Presented:
    """One frame's capsules, reach and menu, the screen and scale it is shown at, and shared material observations.

    Frost remains with the native bar publisher, which owns its composition shadow.
    """

    drawn: tuple[Drawn, ...]
    height: float
    opened: Menu | None
    screen: Rect
    scale: float
    frost: Frost = field(kw_only=True)
    contrast: bool = field(kw_only=True)
    glass: bool = field(kw_only=True)
    shell_look: Look = field(kw_only=True)


def radius(height: float) -> float:
    """The menu keeps a larger radius, concentric with its rows."""
    return SIZES.menu.radius if expanded(height) else SIZES.bar.radius


def expanded(height: float) -> bool:
    """Taller than a capsule's row: the capsule shows the menu."""
    return height > SIZES.capsule.height + 0.5


def visibility(presence: float) -> float:
    """Glass and content become opaque before a capsule reaches its full width."""
    return min(1.0, max(0.0, presence * 1.6))


def animated(part: Part) -> bool:
    """Parts that move on their own, painted every frame rather than kept as a still."""
    match part:
        case Marker.DOTS | Marker.WAVE:
            return True
        case _:
            return False


def controls(content: Content) -> tuple[tuple[Control, float], ...]:
    """The controls a capsule shows, with their left edges."""

    def control(spot: Spot) -> tuple[tuple[Control, float], ...]:
        match spot.part:
            case Control() as part:
                return ((part, spot.x),)
            case _:
                return ()

    return tuple(found for spot in content.spots for found in control(spot))


@lru_cache(maxsize=32)
def _veil(look: GlassLook, frost: Frost) -> Veil:
    """The bar owner retains bounded immutable composition publication values.

    Rebuilding their stops and veil added 1.50 KB at p95 per frame in the
    island benchmark; geometry still changes independently on every frame.
    """
    return Veil(look.veil.color, look.veil.opacity, rim_stops(look.rim), appearance.FROSTS[frost].shadow)


def pane(drawn: Drawn, presented: Presented) -> Pane | None:
    match drawn.look:
        case GlassLook() as look:
            box = drawn.framed.box
            return Pane(
                drawn.view.key.name,
                box.on_device(presented.scale),
                radius(box.height) * presented.scale,
                visibility(drawn.framed.presence),
                _veil(look, presented.frost),
            )
        case SolidLook():
            return None
        case _:
            assert_never(drawn.look)


class ControlButton(KeyboardFocus):
    """A circle concentric with its capsule; its model decides whether it is persistent or revealed."""

    def __init__(self, capsule: Capsule, control: Control) -> None:
        super().__init__(capsule)
        self.capsule = capsule
        self.control = control
        side = round(SIZES.capsule.control)
        self.setFixedSize(side, side)
        self.setToolTip(control.label)
        self.setAccessibleName(control.label)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.clicked.connect(self.pressed_control)

    def update_control(self, control: Control) -> None:
        """Status changes retain the keyboard's current child instead of replacing it."""
        if self.control != control:
            self.control = control
            self.setToolTip(control.label)
            self.setAccessibleName(control.label)
            self.update()

    def pressed_control(self) -> None:
        self.capsule.press(self.control.action)

    @override
    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        lettering = self.capsule.drawn.look.lettering
        self.paint_round(painter, lettering, selected=False)
        symbol = round(SIZES.capsule.icon)
        inset = (self.width() - symbol) // 2
        paint_icon(painter, self.control.icon, lettering.ink, QtCore.QRect(inset, inset, symbol, symbol))


def track(bounds: QtCore.QRectF) -> QtCore.QRectF:
    """The sound slider's bar: beside its speaker symbol, under its label."""
    return QtCore.QRectF(38, bounds.height() - 20, bounds.width() - 52, 6)


def sound_reading(slider: Slider) -> str:
    if slider.level is None:
        return "unavailable"
    return f"{round(slider.level * 100)}%" + (", muted" if slider.muted else "")


class MenuCell(QtWidgets.QAbstractButton):
    """One tile of the expanded capsule. An activity card stops only from its Stop circle;
    the sound slider sets the volume where it is pressed or dragged; a tray icon takes right clicks too."""

    def __init__(self, capsule: Capsule, tile: Tile) -> None:
        super().__init__(capsule)
        self.capsule = capsule
        self.tile = tile
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # The window navigates; cells show its selection.
        self.clicked.connect(self.picked)
        self.describe()

    def describe(self) -> None:
        match self.tile.cell.entry:
            case Live(label=label, detail=detail):
                name = " · ".join(part for part in (label, detail, "Stop recording") if part)
            case Item(label=label, key=key):
                name = f"{label} · {key}" if key else label
            case Toggle(label=label, detail=detail):
                name = f"{label}: {detail}"
            case Slider(label=label) as slider:
                name = f"{label}: {sound_reading(slider)}"
            case TrayIcon(label=label):
                name = label
            case _:
                assert_never(self.tile.cell.entry)
        if self.accessibleName() != name:
            self.setAccessibleName(name)
        # An icon alone needs its name under the pointer; labelled cells already show theirs.
        match self.tile.cell.entry:
            case TrayIcon():
                tip = name
            case _:
                tip = ""
        if self.toolTip() != tip:
            self.setToolTip(tip)

    def update_tile(self, tile: Tile) -> None:
        if tile != self.tile:
            self.tile = tile
            self.describe()
            self.update()

    def picked(self) -> None:
        self.capsule.window_.report(Picked(self.tile.index))

    def stop_circle(self) -> QtCore.QRectF:
        return QtCore.QRectF(self.width() - 34, (self.height() - 28) / 2, 28, 28)

    @override
    def hitButton(self, pos: QtCore.QPoint) -> bool:
        match self.tile.cell.entry:
            case Live():
                return self.stop_circle().contains(QtCore.QPointF(pos))
            case Slider():
                return False  # The slider takes the pointer itself rather than clicking.
            case Item() | Toggle() | TrayIcon():
                return super().hitButton(pos)
            case _:
                assert_never(self.tile.cell.entry)

    def slide(self, pos: QtCore.QPointF) -> None:
        match self.tile.cell.entry:
            case Slider(level=float()):
                bar = track(QtCore.QRectF(self.rect()))
                self.capsule.window_.report(VolumeSet(round(min(1.0, max(0.0, (pos.x() - bar.left()) / bar.width())), 2)))
            case _:
                pass

    @override
    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        super().mousePressEvent(event)
        self.slide(event.position())
        event.accept()  # A miss on a cell stays in the menu, rather than reaching the capsule beneath it.

    @override
    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
        super().mouseMoveEvent(event)
        if event.buttons() & Qt.MouseButton.LeftButton:
            self.slide(event.position())
        event.accept()

    @override
    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        super().mouseReleaseEvent(event)
        match self.tile.cell.entry:
            case TrayIcon(slot=slot) if event.button() is Qt.MouseButton.RightButton and self.rect().contains(event.position().toPoint()):
                self.capsule.window_.report(TrayClicked(slot, Click.RIGHT))
            case _:
                pass
        event.accept()

    @override
    def enterEvent(self, event: QtGui.QEnterEvent) -> None:
        super().enterEvent(event)
        self.capsule.window_.report(Selected(self.tile.index))

    @override
    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        lettering, cell = self.capsule.drawn.look.lettering, self.tile.cell
        menu = self.capsule.window_.menu
        chosen = menu is not None and menu.selected == self.tile.index
        bounds = QtCore.QRectF(self.rect())
        corner = bounds.height() / 2 if cell.face is Face.LINK else 12.0
        painter.setPen(Qt.PenStyle.NoPen)
        if cell.face is not Face.LINK:
            painter.setBrush(color(Shade(lettering.ink.color, 0.07)))
            painter.drawRoundedRect(bounds, corner, corner)
        paint_feedback(painter, lettering, bounds, corner, pressed=chosen, hovered=self.underMouse() and cell.face is not Face.CARD)
        match cell.entry:
            case Live() as activity:
                self.paint_live(painter, activity)
            case Toggle() as toggle:
                self.paint_toggle(painter, toggle)
            case Slider() as slider:
                self.paint_slider(painter, slider)
            case Item(icon=name) if cell.face is Face.TOOL:
                self.paint_icon(painter, name, lettering.ink, QtCore.QPointF(bounds.width() / 2 - 8, 12))
                painter.setPen(color(lettering.quiet))
                painter.setFont(inter(11, QtGui.QFont.Weight.Normal))
                painter.drawText(bounds.adjusted(2, 0, -2, -9), Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter, cell.caption)
            case Item(label=label, icon=name, key=key):
                self.paint_icon(painter, name, lettering.quiet, QtCore.QPointF(12, (bounds.height() - 16) / 2))
                painter.setFont(font(strong=False))
                painter.setPen(color(lettering.ink))
                painter.drawText(bounds.adjusted(36, 0, -10, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, label)
                if key:
                    painter.setPen(color(lettering.quiet))
                    painter.drawText(bounds.adjusted(0, 0, -12, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, key)
            case TrayIcon(slot=slot):
                self.paint_tray(painter, slot, bounds)
            case _:
                assert_never(cell.entry)

    def paint_symbol(self, painter: QtGui.QPainter, name: str, *, on: bool) -> None:
        """A symbol in its own circle at the cell's leading edge, filled with the accent while its setting is on."""
        lettering = self.capsule.drawn.look.lettering
        # Tiles and toggles share one leading edge, so their symbols line up down the grid.
        at = QtCore.QPointF(4, (self.height() - 28) / 2)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color(self.capsule.signal(GLASS_ACCENT, lettering.ink) if on else Shade(lettering.ink.color, 0.12)))
        painter.drawEllipse(QtCore.QRectF(at.x(), at.y(), 28, 28))
        ink = self.capsule.signal("#ffffff", lettering.press) if on else lettering.ink
        self.paint_icon(painter, name, ink, QtCore.QPointF(at.x() + 6, at.y() + 6))

    def paint_toggle(self, painter: QtGui.QPainter, toggle: Toggle) -> None:
        self.paint_symbol(painter, toggle.icon, on=toggle.on)
        self.paint_lines(painter, QtCore.QRectF(38, 0, self.width() - 42, self.height()), toggle.label, toggle.detail, strong=False)

    def paint_lines(self, painter: QtGui.QPainter, area: QtCore.QRectF, title: str, detail: str, *, strong: bool) -> None:
        """A title in ink over a quieter detail line, meeting at the cell's middle."""
        lettering, middle = self.capsule.drawn.look.lettering, area.height() / 2
        painter.setFont(font(strong=strong))
        painter.setPen(color(lettering.ink))
        painter.drawText(QtCore.QRectF(area.left(), 0, area.width(), middle + 1), Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignLeft, title)
        painter.setFont(inter(11, QtGui.QFont.Weight.Normal))
        painter.setPen(color(lettering.quiet))
        painter.drawText(QtCore.QRectF(area.left(), middle, area.width(), middle), Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft, detail)

    def paint_slider(self, painter: QtGui.QPainter, slider: Slider) -> None:
        lettering, bounds = self.capsule.drawn.look.lettering, QtCore.QRectF(self.rect())
        painter.setFont(font(strong=True))
        painter.setPen(color(lettering.ink))
        painter.drawText(QtCore.QRectF(12, 8, bounds.width() - 24, 16), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, slider.label)
        bar = track(bounds)
        symbol = "speaker-muted" if slider.muted else "speaker-on"
        self.paint_icon(painter, symbol, lettering.quiet, QtCore.QPointF(12, bar.center().y() - 8))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color(Shade(lettering.ink.color, 0.16)))
        painter.drawRoundedRect(bar, 3, 3)
        if slider.level is None:
            return
        filled = QtCore.QRectF(bar.left(), bar.top(), bar.width() * slider.level, bar.height())
        painter.setBrush(color(lettering.quiet if slider.muted else self.capsule.signal(GLASS_ACCENT, lettering.ink)))
        painter.drawRoundedRect(filled, 3, 3)
        painter.setBrush(color(self.capsule.signal("#ffffff", lettering.ink)))
        painter.drawEllipse(QtCore.QPointF(filled.right(), bar.center().y()), 7, 7)

    def paint_live(self, painter: QtGui.QPainter, activity: Live) -> None:
        """An activity card: its glyph, its reading, and its Stop circle."""
        lettering, bounds = self.capsule.drawn.look.lettering, QtCore.QRectF(self.rect())
        paint_dot(painter, color(self.capsule.signal(RED, lettering.ink)), QtCore.QPointF(20, bounds.height() / 2), 5)
        detail = QtGui.QFontMetricsF(inter(11, QtGui.QFont.Weight.Normal)).elidedText(
            activity.detail, Qt.TextElideMode.ElideRight, bounds.width() - 84
        )
        self.paint_lines(painter, QtCore.QRectF(40, 0, bounds.width() - 80, bounds.height()), activity.label, detail, strong=True)
        circle = self.stop_circle()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color(lettering.press if self.isDown() else lettering.hover))
        painter.drawEllipse(circle)
        paint_icon(painter, "stop", lettering.ink, circle.adjusted(6, 6, -6, -6).toRect())

    def paint_tray(self, painter: QtGui.QPainter, slot: int, bounds: QtCore.QRectF) -> None:
        """The application's own image, one image pixel per screen pixel up to 22 px, on whole device pixels.

        Windows asks applications for tray icons at its small-icon size for the
        screen's scale, so drawing them unscaled keeps them as sharp as the taskbar.
        One without an image reads as a window.
        """
        images = self.capsule.window_.tray_images
        image = images[slot] if slot < len(images) else None
        if image is None:
            self.paint_icon(painter, "window", self.capsule.drawn.look.lettering.ink, bounds.center() - QtCore.QPointF(8, 8))
            return
        scale = self.devicePixelRatioF()
        side = min(22.0, image.width() / scale)
        left, top = on_pixels(bounds.center().x() - side / 2, scale), on_pixels(bounds.center().y() - side / 2, scale)
        painter.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawPixmap(QtCore.QRectF(left, top, side, side), image, QtCore.QRectF(image.rect()))

    def paint_icon(self, painter: QtGui.QPainter, name: str, ink: Shade, at: QtCore.QPointF) -> None:
        paint_icon(painter, name, ink, QtCore.QRect(round(at.x()), round(at.y()), 16, 16))


class Capsule(KeyboardFocus):
    """One capsule: its strip to the screen edge, its shape, and its parts.

    A press acts on what the capsule shows; the bar's owner decides what that is.
    """

    def __init__(self, window: BarWindow, drawn: Drawn, *, contrast: bool) -> None:
        super().__init__(window)
        self.window_ = window
        self.key = drawn.view.key
        self.drawn = drawn
        """The frame it shows: its view, content, any content fading out, how it reads and its presence."""
        self.contrast = contrast
        self.controls = tuple(ControlButton(self, control) for control, _ in controls(drawn.content))
        self.cells: tuple[MenuCell, ...] = ()
        self.placed: tuple[QtCore.QRect, float, float, Content, tuple[Tile, ...]] | None = None
        self.stills: frozendict[tuple[Content, Look, bool, float], QtGui.QPixmap] = frozendict()
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.clicked.connect(self.pressed_capsule)
        self.describe(drawn.view)

    def press(self, action: Action) -> None:
        self.window_.report(Pressed(action))

    def signal(self, hue: str, ink: Shade) -> Shade:
        """A signal's own hue; high contrast keeps the system colours instead of adding one."""
        return ink if self.contrast else Shade(hue)

    def pressed_capsule(self) -> None:
        self.press(self.drawn.view.action)

    def describe(self, view: CapsuleView) -> None:
        self.setToolTip("" if view.action is Action.CLOSE_MENU else view.label)
        self.setAccessibleName(view.label)

    def show_view(self, drawn: Drawn, *, contrast: bool) -> None:
        """Show `drawn`; a frame that only moves the capsule changes nothing it paints."""
        before, self.drawn = self.drawn, drawn
        if contrast == self.contrast and replace(before, framed=replace(before.framed, box=drawn.framed.box)) == drawn:
            return
        if before.view.label != drawn.view.label:
            # Each change raises an accessibility event; frames of a fade keep the label.
            self.describe(drawn.view)
        self.contrast = contrast
        wanted = controls(drawn.content)
        if tuple(button.control.action for button in self.controls) != tuple(control.action for control, _ in wanted):
            for button in self.controls:
                # Deletion waits for the event loop; the replaced control must leave this frame.
                button.hide()
                button.deleteLater()
            self.controls = tuple(ControlButton(self, control) for control, _ in wanted)
        for button, (control, _) in zip(self.controls, wanted, strict=True):
            button.update_control(control)
        self.update()

    def show_menu(self, menu: Menu | None) -> None:
        """The expanded capsule's cells, pooled for as long as the menu shows the same grid."""
        laid = tiles(menu, SIZES.menu) if menu is not None else ()
        if len(laid) != len(self.cells) or any(cell.tile.cell.entry != tile.cell.entry for cell, tile in zip(self.cells, laid, strict=False)):
            for cell in self.cells:
                cell.hide()
                cell.deleteLater()
            self.cells = tuple(MenuCell(self, tile) for tile in laid)
        for cell, tile in zip(self.cells, laid, strict=True):
            cell.update_tile(tile)
            cell.update()

    def place_cells(self) -> None:
        top = round(SIZES.bar.top)
        left = (self.width() - SIZES.menu.width) / 2
        for cell in self.cells:
            tile = cell.tile
            cell.setGeometry(round(left + tile.x), top + round(tile.y), round(tile.width), round(tile.height))
            cell.setVisible(top + tile.y + tile.height <= self.height())

    def place_controls(self) -> None:
        shift = self.shift(self.drawn.content)
        for button, (_, x) in zip(self.controls, controls(self.drawn.content), strict=True):
            button.move(round(shift + x), round(SIZES.bar.top + SIZES.capsule.inset))
            button.setVisible(self.drawn.fade > 0.5 and visibility(self.drawn.framed.presence) == 1)

    def shift(self, content: Content) -> float:
        """Content keeps its measured layout, centred while the capsule's width morphs around it."""
        return (self.width() - content.width) / 2

    def frame(self, framed: Framed) -> None:
        """The widget spans the edge strip and the capsule below it."""
        top = round(SIZES.bar.top)
        geometry = QtCore.QRect(round(framed.box.x), 0, max(1, round(framed.box.width)), top + round(framed.box.height))
        placed = (geometry, self.drawn.fade, self.drawn.framed.presence, self.drawn.content, tuple(cell.tile for cell in self.cells))
        if placed == self.placed:
            return
        self.placed = placed
        self.setGeometry(geometry)
        self.place_controls()
        self.place_cells()

    def update_indicators(self) -> None:
        """Repaint only the live indicators (dots, trace); the rest of the capsule is unchanged."""
        shift = self.shift(self.drawn.content)
        for spot in self.drawn.content.spots:
            if animated(spot.part):
                self.update(
                    QtCore.QRect(math.floor(shift + spot.x) - 2, round(SIZES.bar.top), math.ceil(spot.width) + 4, round(SIZES.capsule.height))
                )

    @override
    def enterEvent(self, event: QtGui.QEnterEvent) -> None:
        super().enterEvent(event)
        self.window_.report(Hovered(self.key))
        self.update()

    @override
    def leaveEvent(self, event: QtCore.QEvent) -> None:
        super().leaveEvent(event)
        self.window_.report(Hovered(None))
        self.update()

    @override
    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        top, middle = SIZES.bar.top, SIZES.bar.top + SIZES.capsule.height / 2
        shape = QtCore.QRectF(0, top, self.width(), self.height() - top)
        corner = min(radius(shape.height()), shape.height() / 2)
        path = outline(shape, corner)
        strip = QtGui.QPainterPath()
        strip.addRect(QtCore.QRectF(0, 0, self.width(), top))
        painter.fillPath(strip, hit())
        alpha = visibility(self.drawn.framed.presence)
        paint_capsule(painter, path, self.drawn.look, alpha)
        drawn = self.drawn
        flat = not expanded(drawn.content.height)
        paint_feedback(
            painter,
            drawn.look.lettering,
            shape,
            corner,
            pressed=self.isDown() and flat,
            hovered=self.underMouse() and flat,
            ringed=self.focus_ringed,
            inset=1.5,
        )
        painter.setClipPath(path)
        layers: tuple[tuple[Content, float], ...] = (
            ((drawn.previous, alpha * (1 - drawn.fade)), (drawn.content, alpha * drawn.fade))
            if drawn.previous is not None
            else ((drawn.content, alpha),)
        )
        for content, opacity in layers:
            if opacity <= 0:
                continue
            painter.save()
            painter.setOpacity(opacity)
            painter.translate(self.shift(content), 0)
            painter.drawPixmap(QtCore.QPointF(0, 0), self.still(content))
            for spot in content.spots:
                if animated(spot.part):
                    self.paint_part(painter, spot, middle)
            painter.restore()

    def still(self, content: Content) -> QtGui.QPixmap:
        """The content's unmoving parts, rendered once: a morphing capsule blits them each frame."""
        key = (content, self.drawn.look, self.contrast, self.devicePixelRatioF())
        cached = self.stills.get(key)
        if cached is not None:
            return cached
        scale = self.devicePixelRatioF()
        top, row = SIZES.bar.top, SIZES.capsule.height
        image = QtGui.QPixmap(max(1, math.ceil(content.width * scale)), math.ceil((top + max(row, content.height)) * scale))
        image.setDevicePixelRatio(scale)
        image.fill(Qt.GlobalColor.transparent)
        painter = QtGui.QPainter(image)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        for spot in content.spots:
            if not animated(spot.part):
                self.paint_part(painter, spot, top + row / 2)
        painter.end()
        # Only the content showing now and the content fading out are kept.
        kept = {(c, self.drawn.look, self.contrast, scale) for c in (self.drawn.content, self.drawn.previous) if c is not None}
        self.stills = frozendict({**{k: v for k, v in self.stills.items() if k in kept}, key: image})
        return image

    def paint_part(self, painter: QtGui.QPainter, spot: Spot, middle: float) -> None:
        lettering = self.drawn.look.lettering
        match spot.part:
            case Text(text=text, tone=tone):
                painter.setFont(font(strong=False))
                painter.setPen(color(reading(lettering, tone, contrast=self.contrast)))
                row = QtCore.QRectF(spot.x, SIZES.bar.top, spot.width + 1, SIZES.capsule.height)
                painter.drawText(row, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)
            case Glyph(name=name, tone=tone):
                side = round(SIZES.capsule.icon)
                paint_icon(
                    painter, name, reading(lettering, tone, contrast=self.contrast), QtCore.QRect(round(spot.x), round(middle - side / 2), side, side)
                )
            case Control():
                pass  # A child button paints it.
            case Marker.WAVE:
                trace = color(reading(lettering, Tone.INK, contrast=self.contrast))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(trace)
                for index, sample in enumerate(self.window_.trace()):
                    height = 3 + sample * 13
                    painter.drawRoundedRect(QtCore.QRectF(spot.x + index * 4, middle - height / 2, 2, height), 1, 1)
            case Marker.DOTS:
                self.paint_dots(painter, spot, middle)
            case Marker.DOT:
                red = color(self.signal(RED, lettering.ink))
                halo = QtGui.QColor(red)
                halo.setAlphaF(0.25)
                centre = QtCore.QPointF(spot.x + 4, middle)
                paint_dot(painter, halo, centre, 7)
                paint_dot(painter, red, centre, 4)
            case _:
                assert_never(spot.part)

    def paint_dots(self, painter: QtGui.QPainter, spot: Spot, middle: float) -> None:
        """A quick job: three dots pulsing in turn."""
        ink = self.drawn.look.lettering.ink
        cycle = (90 - self.window_.spin_angle) % 360 / 360  # One turn of the frame clock per pulse cycle.
        painter.setPen(Qt.PenStyle.NoPen)
        for index in range(3):
            lift = max(0.0, math.sin((cycle - index / 6) * 2 * math.pi))
            painter.setBrush(color(Shade(ink.color, ink.opacity * (0.35 + 0.65 * lift))))
            painter.drawEllipse(QtCore.QPointF(spot.x + 3 + index * 6, middle - lift * 1.5), 2.2, 2.2)


class BarWindow(QtWidgets.QWidget):
    """The bar's one window: the full width of the primary screen, as tall as the capsules."""

    def __init__(self, report: Callable[[Event], None], composition: DesktopComposition | None) -> None:
        super().__init__()
        self.report = report
        """Everything the person does in the bar, as the bar's events."""
        self.composition = composition
        self.menu: Menu | None = None
        self.capsules: Mapping[Key, Capsule] = frozendict()
        self.spin_angle = 90.0
        # Qt owns the painted trace; samples arrive from the bar's audio meter.
        self.samples: deque[float] = deque([0.0] * SIZES.capsule.wave_bars, maxlen=SIZES.capsule.wave_bars)
        self.wave_from: tuple[float, ...] = tuple(self.samples)
        self.wave_progress = 1.0
        # This UI owner retains the immutable last application frame to avoid
        # native layout and glass work for unchanged indicator-only redraws.
        self.presentation: Presented | None = None
        self.scene: GlassScene | None = None
        self.panes: tuple[Pane, ...] = ()
        self.pager = Pager(self)
        # The bar's latest tray snapshot and Qt copies of its images, for the menu's tray cells.
        self.tray: tuple[Entry, ...] = ()
        self.tray_images: tuple[QtGui.QPixmap | None, ...] = ()
        self.glass = False
        tool_window(self, BAR_WINDOW, on_top=True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)  # The open menu takes the keyboard here.
        borderless(int(self.winId()))
        windows.allow_activation(int(self.winId()), allowed=False)
        # Several changes in one Qt turn publish one final glass frame.
        self.glass_timer = QtCore.QTimer(self)
        self.glass_timer.setSingleShot(True)
        self.glass_timer.timeout.connect(self.publish_glass)
        # Native activation can briefly report inactive then active while Qt
        # settles the first opening. Dismiss only after one frame of stable
        # inactivity; a real focus transfer still closes the menu promptly.
        self.deactivation_timer = QtCore.QTimer(self)
        self.deactivation_timer.setTimerType(QtCore.Qt.TimerType.PreciseTimer)
        self.deactivation_timer.setSingleShot(True)
        self.deactivation_timer.timeout.connect(self.dismiss_inactive)

    def show_tray(self, entries: tuple[Entry, ...]) -> None:
        """Adopt a tray snapshot, repainting open tray cells."""
        if entries == self.tray:
            return
        self.tray = entries
        self.tray_images = tuple(pixmap(entry.image) if entry.image is not None else None for entry in entries)
        status = self.capsules.get(Key.STATUS)
        for cell in status.cells if status is not None else ():
            cell.update()

    def tray_locations(self) -> tuple[Located, ...]:
        """Where the open menu shows each tray icon, in device pixels, for applications anchoring their flyouts."""
        status = self.capsules.get(Key.STATUS)
        if status is None or not status.isVisible():
            return ()
        outer, scale = windows.outer_rect(int(self.winId())), self.devicePixelRatioF()

        def located(cell: MenuCell, slot: int) -> tuple[Located, ...]:
            if slot >= len(self.tray) or not cell.isVisible():
                return ()
            point = cell.mapTo(self, QtCore.QPoint())
            return (Located(self.tray[slot], Box(point.x(), point.y(), cell.width(), cell.height()).on_screen(outer, scale)),)

        def slot(cell: MenuCell) -> tuple[Located, ...]:
            match cell.tile.cell.entry:
                case TrayIcon(slot=index):
                    return located(cell, index)
                case _:
                    return ()

        return tuple(found for cell in status.cells for found in slot(cell))

    def measure(self, view: CapsuleView) -> Content:
        def width(text: Text) -> float:
            return math.ceil(QtGui.QFontMetricsF(font(strong=False)).horizontalAdvance(text.text))

        return arrange(view.slots, width, SIZES)

    def capsule(self, drawn: Drawn, *, contrast: bool) -> Capsule:
        """The pooled capsule for `drawn`'s key, showing it."""
        existing = self.capsules.get(drawn.view.key)
        if existing is not None:
            existing.show_view(drawn, contrast=contrast)
            return existing
        created = Capsule(self, drawn, contrast=contrast)
        self.capsules = frozendict({**self.capsules, drawn.view.key: created})
        return created

    def present(self, presented: Presented) -> None:
        """Show exactly these capsules where their frames put them; other pooled capsules hide."""
        if presented == self.presentation:
            return
        area = presented.screen
        height = round(SIZES.bar.top) + math.ceil(presented.height)
        if self.geometry() != QtCore.QRect(area.left, area.top, area.width, height):
            self.setGeometry(area.left, area.top, area.width, height)
        self.menu = presented.opened
        keys = frozenset(each.view.key for each in presented.drawn)
        for each in presented.drawn:
            capsule = self.capsule(each, contrast=presented.contrast)
            if each.view.key is Key.STATUS:
                capsule.show_menu(self.menu if expanded(each.content.height) else None)
            capsule.frame(each.framed)
            capsule.show()
        for key, capsule in self.capsules.items():
            if key not in keys:
                capsule.hide()
        pager = self.pager
        # The pager runs from the screen's edge, stopping before the leftmost capsule.
        pager.place(12, math.floor(min((each.framed.box.x for each in presented.drawn), default=area.width / 2)) - 12)
        pager.apply_look(presented.shell_look)
        self.glass = presented.glass
        self.panes = tuple(found for each in presented.drawn if (found := pane(each, presented)))
        scale = presented.scale
        match presented.shell_look:
            case GlassLook() as shell_look if pager.isVisibleTo(self):
                bounds = Box(pager.x(), pager.y(), pager.width(), pager.height()).on_device(scale)
                self.panes = (*self.panes, Pane("desktops", bounds, SIZES.bar.radius * scale, 1, _veil(shell_look, presented.frost)))
            case GlassLook() | SolidLook():
                pass
        if not self.glass_timer.isActive():
            self.glass_timer.start(0)
        self.presentation = presented

    def trace(self) -> Iterator[float]:
        """Interpolate the displayed history between the meter's 50 ms samples."""
        progress = self.wave_progress
        return (before + (after - before) * progress for before, after in zip(self.wave_from, self.samples, strict=True))

    @override
    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        keys = {
            Qt.Key.Key_Up: island_menu.Key.UP,
            Qt.Key.Key_Down: island_menu.Key.DOWN,
            Qt.Key.Key_Left: island_menu.Key.LEFT,
            Qt.Key.Key_Right: island_menu.Key.RIGHT,
            Qt.Key.Key_Return: island_menu.Key.ENTER,
            Qt.Key.Key_Enter: island_menu.Key.ENTER,
            Qt.Key.Key_Space: island_menu.Key.ENTER,
            Qt.Key.Key_Escape: island_menu.Key.ESCAPE,
        }
        if self.menu is None:
            super().keyPressEvent(event)
            return
        named = keys.get(Qt.Key(event.key()))
        if named is not None:
            self.report(MenuKey(named))
        elif event.text().isalpha():
            self.report(MenuKey(island_menu.Letter(event.text()[0])))
        else:
            super().keyPressEvent(event)

    @override
    def changeEvent(self, event: QtCore.QEvent) -> None:
        super().changeEvent(event)
        if event.type() is QtCore.QEvent.Type.ActivationChange:
            if self.isActiveWindow():
                self.deactivation_timer.stop()
            elif self.menu is not None and not self.deactivation_timer.isActive():
                self.deactivation_timer.start(16)

    def dismiss_inactive(self) -> None:
        if self.menu is not None and not self.isActiveWindow():
            self.report(Deactivated())

    def bounds(self, key: Key) -> Rect | None:
        """A shown capsule's screen rectangle in device pixels. Capsules stay alien widgets:
        a native child window would break the bar's per-pixel hit-testing."""
        capsule = self.capsules.get(key)
        if capsule is None or not capsule.isVisible() or not self.isVisible():
            return None
        shape, strip = capsule.geometry(), SIZES.bar.top
        area = Box(shape.x(), shape.y() + strip, shape.width(), shape.height() - strip)
        return area.on_screen(windows.outer_rect(int(self.winId())), self.devicePixelRatioF())

    def publish_glass(self) -> None:
        if not self.isVisible() or not self.glass:
            if self.scene is not None:
                self.scene.hide()
            return
        if self.scene is None and self.composition is not None:
            try:
                self.scene = self.composition.scene("Workspace · Island glass")
            except OSError as error:
                log(f"Island glass unavailable; using the solid material: {error}")
        if self.scene is None:
            return
        outer = windows.outer_rect(int(self.winId()))
        margin = round(SIZES.bar.shadow * self.devicePixelRatioF())
        self.scene.place(Rect(outer.left - margin, outer.top, outer.right + margin, outer.bottom + margin), self.devicePixelRatioF())
        self.scene.publish(tuple(Pane(pane.key, shifted(pane.bounds, margin), pane.radius, pane.opacity, pane.veil) for pane in self.panes))
        self.scene.show(int(self.winId()))

    def dispose(self) -> None:
        self.glass_timer.stop()
        self.deactivation_timer.stop()
        self.menu = None
        self.hide()
        if self.scene is not None:
            self.scene.close()
            self.scene = None
        self.deleteLater()


def shifted(bounds: Rect, margin: int) -> Rect:
    return Rect(bounds.left + margin, bounds.top, bounds.right + margin, bounds.bottom)


def paint_dot(painter: QtGui.QPainter, colour: QtGui.QColor, centre: QtCore.QPointF, radius: float) -> None:
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(colour)
    painter.drawEllipse(centre, radius, radius)
