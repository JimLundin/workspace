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
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Final, Protocol, assert_never, override

lazy from PySide6 import QtCore, QtGui, QtWidgets
lazy from PySide6.QtCore import Qt

import desktop_ui.request_panel
from components import BAR_WINDOW
from desktop_ui import island_menu
from desktop_ui.agent_progress import Phase
from desktop_ui.components import appearance, typeface
from desktop_ui.components.appearance import GLASS_ACCENT, RED, GlassLook, Look, Shade, SolidLook, look, reading, rim_stops
from desktop_ui.components.meaning import Tint, Tone
from desktop_ui.components.text import color
from desktop_ui.island_layout import (
    HEIGHT,
    MENU_HEAD,
    MENU_PAD,
    MENU_RADIUS,
    MENU_WIDTH,
    WAVE_BARS,
    Content,
    Framed,
    Spot,
    Tile,
    arrange,
    tiles,
)
from desktop_ui.island_menu import Face, Item, Live, Menu, Slider, Toggle, TrayIcon
from desktop_ui.island_model import Action, Badge, CapsuleView, Control, Glyph, Key, Marker, Part, Spinner, Text
from desktop_ui.qt_runtime import prepare
from desktop_ui.qt_ui import EventLoop
from desktop_ui.request_panel import RequestActions, RequestPanel
from desktop_ui.shell_surface import ShellSections, pixmap
from desktop_ui.vector_icons import icon
from desktop_ui.view_publication import log_view
from winapi import windows
from winapi.appearance import Frost, Material
from winapi.composition import GlassScene, borderless
from winapi.shapes import Pane, Rect, Veil
from winapi.tray_host import Click, Entry, Located

prepare()

TOP: Final = 8  # The island floats this far below the screen edge.
RADIUS: Final = 17
SHADOW: Final = 40  # Room below and beside the capsules for their composed shadow.


class KeyboardFocus(QtWidgets.QAbstractButton):
    """A button that rings itself only for keyboard focus, as `:focus-visible` does."""

    def __init__(self, parent: QtWidgets.QWidget) -> None:
        super().__init__(parent)
        self.ringed = False  # Qt owns focus; the widget remembers only how focus arrived.

    @override
    def focusInEvent(self, event: QtGui.QFocusEvent) -> None:
        super().focusInEvent(event)
        self.ringed = event.reason() in (Qt.FocusReason.TabFocusReason, Qt.FocusReason.BacktabFocusReason)
        self.update()

    @override
    def focusOutEvent(self, event: QtGui.QFocusEvent) -> None:
        super().focusOutEvent(event)
        self.ringed = False
        self.update()


class Owner(Protocol):
    """What the bar window reports to the bar's owner."""

    def press(self, action: Action) -> None: ...
    def hover(self, key: Key | None) -> None: ...
    def select(self, index: int) -> None: ...
    def pick(self, index: int) -> None: ...
    def volume(self, level: float) -> None: ...
    def tray(self, slot: int, click: Click) -> None: ...
    def scroll(self, delta: int) -> None:
        """A horizontal wheel event over the bar, in eighths of a degree."""

    def key(self, press: island_menu.Press) -> None: ...
    def deactivated(self) -> None: ...
    def request_actions(self) -> RequestActions | None: ...
    def render(self) -> None: ...


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
    """One frame's capsules, reach, menu and shared material observations.

    Frost remains with the native bar publisher, which owns its composition shadow.
    """

    drawn: tuple[Drawn, ...]
    height: float
    menu: Menu | None
    frost: Frost = field(kw_only=True)
    contrast: bool = field(kw_only=True)
    glass: bool = field(kw_only=True)
    request: Phase | None = None
    shell_look: Look = field(kw_only=True)


def radius(height: float) -> float:
    """The menu keeps a larger radius, concentric with its rows."""
    return MENU_RADIUS if height > HEIGHT + 0.5 else RADIUS


def visibility(presence: float) -> float:
    """Glass and content become opaque before a capsule reaches its full width."""
    return min(1.0, max(0.0, presence * 1.6))


def animated(part: Part) -> bool:
    """Parts that move on their own, painted every frame rather than kept as a still."""
    match part:
        case Spinner() | Marker.DOTS | Marker.WAVE:
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
    shadow = 0.14 if frost is Frost.BRIGHT else 0.36
    return Veil(look.veil.color, look.veil.opacity, rim_stops(look.rim), shadow)


def pane(drawn: Drawn, frost: Frost, scale: float) -> Pane | None:
    match drawn.look:
        case GlassLook() as look:
            box = drawn.framed.box
            bounds = Rect(round(box.x * scale), round(box.y * scale), round((box.x + box.width) * scale), round((box.y + box.height) * scale))
            return Pane(drawn.view.key.name, bounds, radius(box.height) * scale, visibility(drawn.framed.presence), _veil(look, frost))
        case SolidLook():
            return None
        case _:
            assert_never(drawn.look)


@lru_cache(maxsize=2)
def font(*, strong: bool) -> QtGui.QFont:
    value = QtGui.QFont(typeface.FAMILY)
    value.setPixelSize(12)
    value.setWeight(QtGui.QFont.Weight.DemiBold if strong else QtGui.QFont.Weight.Medium)
    value.setFeature(QtGui.QFont.Tag("tnum"), 1)  # Readings keep their width as digits change.
    return value


@lru_cache(maxsize=1)
def caption_font() -> QtGui.QFont:
    value = QtGui.QFont(typeface.FAMILY)
    value.setPixelSize(11)
    value.setWeight(QtGui.QFont.Weight.Normal)
    return value


@lru_cache(maxsize=1)
def heading_font() -> QtGui.QFont:
    value = QtGui.QFont(typeface.FAMILY)
    value.setPixelSize(14)
    value.setWeight(QtGui.QFont.Weight.DemiBold)
    return value


@lru_cache(maxsize=2)
def badge_font() -> QtGui.QFont:
    value = QtGui.QFont(typeface.FAMILY)
    value.setPixelSize(10)
    value.setWeight(QtGui.QFont.Weight.Bold)
    return value


class ControlButton(KeyboardFocus):
    """A concentric 28 px circle; its model decides whether it is persistent or revealed."""

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

    def update_control(self, control: Control) -> None:
        """Status changes retain the keyboard's current child instead of replacing it."""
        if self.control != control:
            self.control = control
            self.setToolTip(control.label)
            self.setAccessibleName(control.label)
            self.update()

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
        if self.hasFocus() and self.ringed:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QtGui.QPen(color(lettering.ink), 1.5))
            painter.drawEllipse(QtCore.QRectF(self.rect()).adjusted(1, 1, -1, -1))
        ink = lettering.ink
        painter.setOpacity(ink.opacity)
        icon(self.control.icon, ink.color).paint(painter, QtCore.QRect(6, 6, 16, 16))


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
            case Live(label=label, detail=detail, stop=stop):
                action = "Stop recording" if stop is island_menu.Command.STOP_RECORDING else "Stop agent work"
                name = " · ".join(part for part in (label, detail, action) if part)
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
        self.capsule.window_.owner.pick(self.tile.index)

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
                self.capsule.window_.owner.volume(round(min(1.0, max(0.0, (pos.x() - bar.left()) / bar.width())), 2))
            case _:
                pass

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        super().mousePressEvent(event)
        self.slide(event.position())
        event.accept()  # A miss on a cell stays in the menu, rather than reaching the capsule beneath it.

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
        super().mouseMoveEvent(event)
        if event.buttons() & Qt.MouseButton.LeftButton:
            self.slide(event.position())
        event.accept()

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        super().mouseReleaseEvent(event)
        match self.tile.cell.entry:
            case TrayIcon(slot=slot) if event.button() is Qt.MouseButton.RightButton and self.rect().contains(event.position().toPoint()):
                self.capsule.window_.owner.tray(slot, Click.RIGHT)
            case _:
                pass
        event.accept()

    def enterEvent(self, event: QtGui.QEnterEvent) -> None:
        super().enterEvent(event)
        self.capsule.window_.owner.select(self.tile.index)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        lettering, cell = self.capsule.look.lettering, self.tile.cell
        menu = self.capsule.window_.menu
        chosen = menu is not None and menu.selected == self.tile.index
        bounds = QtCore.QRectF(self.rect())
        corner = bounds.height() / 2 if cell.face is Face.LINK else 12.0
        painter.setPen(Qt.PenStyle.NoPen)
        if cell.face is not Face.LINK:
            painter.setBrush(color(Shade(lettering.ink.color, 0.07)))
            painter.drawRoundedRect(bounds, corner, corner)
        if chosen or (self.underMouse() and cell.face is not Face.CARD):
            painter.setBrush(color(lettering.press if chosen else lettering.hover))
            painter.drawRoundedRect(bounds, corner, corner)
        ink, quiet = color(lettering.ink), color(lettering.quiet)
        match cell.entry:
            case Live() as activity:
                self.paint_live(painter, activity)
            case Toggle() as toggle:
                self.paint_toggle(painter, toggle)
            case Slider() as slider:
                self.paint_slider(painter, slider)
            case Item(icon=name) if cell.face is Face.TILE:
                self.paint_symbol(painter, name, on=False)
                painter.setPen(ink)
                painter.setFont(font(strong=True))
                painter.drawText(bounds.adjusted(48, 0, -8, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, cell.caption)
            case Item(icon=name) if cell.face is Face.TOOL:
                self.paint_icon(painter, name, ink, QtCore.QPointF(bounds.width() / 2 - 8, 12))
                painter.setPen(quiet)
                painter.setFont(caption_font())
                painter.drawText(bounds.adjusted(2, 0, -2, -9), Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter, cell.caption)
            case Item(label=label, icon=name, key=key):
                self.paint_icon(painter, name, quiet, QtCore.QPointF(12, (bounds.height() - 16) / 2))
                painter.setFont(font(strong=False))
                painter.setPen(ink)
                painter.drawText(bounds.adjusted(36, 0, -10, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, label)
                if key:
                    painter.setPen(quiet)
                    painter.drawText(bounds.adjusted(0, 0, -12, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, key)
            case TrayIcon(slot=slot):
                self.paint_tray(painter, slot, bounds)
            case _:
                assert_never(cell.entry)

    def paint_symbol(self, painter: QtGui.QPainter, name: str, *, on: bool) -> None:
        """A symbol in its own circle at the cell's leading edge, filled with the accent while its setting is on."""
        lettering = self.capsule.look.lettering
        at = QtCore.QPointF(12 if self.tile.cell.face is Face.TILE else 4, (self.height() - 28) / 2)
        painter.setPen(Qt.PenStyle.NoPen)
        if on:
            painter.setBrush(QtGui.QColor(GLASS_ACCENT) if not self.capsule.contrast else color(lettering.ink))
        else:
            painter.setBrush(color(Shade(lettering.ink.color, 0.12)))
        painter.drawEllipse(QtCore.QRectF(at.x(), at.y(), 28, 28))
        ink = (QtGui.QColor("#ffffff") if not self.capsule.contrast else color(lettering.press)) if on else color(lettering.ink)
        self.paint_icon(painter, name, ink, QtCore.QPointF(at.x() + 6, at.y() + 6))

    def paint_toggle(self, painter: QtGui.QPainter, toggle: Toggle) -> None:
        lettering, bounds = self.capsule.look.lettering, QtCore.QRectF(self.rect())
        self.paint_symbol(painter, toggle.icon, on=toggle.on)
        middle = bounds.height() / 2
        painter.setFont(font(strong=False))
        painter.setPen(color(lettering.ink))
        text = QtCore.QRectF(38, 0, bounds.width() - 42, middle + 1)
        painter.drawText(text, Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignLeft, toggle.label)
        painter.setFont(caption_font())
        painter.setPen(color(lettering.quiet))
        painter.drawText(
            QtCore.QRectF(38, middle, bounds.width() - 42, middle), Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft, toggle.detail
        )

    def paint_slider(self, painter: QtGui.QPainter, slider: Slider) -> None:
        lettering, bounds = self.capsule.look.lettering, QtCore.QRectF(self.rect())
        painter.setFont(font(strong=True))
        painter.setPen(color(lettering.ink))
        painter.drawText(QtCore.QRectF(12, 8, bounds.width() - 24, 16), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, slider.label)
        bar = track(bounds)
        symbol = "speaker-muted" if slider.muted else "speaker-on"
        self.paint_icon(painter, symbol, color(lettering.quiet), QtCore.QPointF(12, bar.center().y() - 8))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color(Shade(lettering.ink.color, 0.16)))
        painter.drawRoundedRect(bar, 3, 3)
        if slider.level is None:
            return
        filled = QtCore.QRectF(bar.left(), bar.top(), bar.width() * slider.level, bar.height())
        painter.setBrush(
            color(lettering.quiet) if slider.muted else QtGui.QColor(GLASS_ACCENT) if not self.capsule.contrast else color(lettering.ink)
        )
        painter.drawRoundedRect(filled, 3, 3)
        painter.setBrush(QtGui.QColor("#ffffff") if not self.capsule.contrast else color(lettering.ink))
        painter.drawEllipse(QtCore.QPointF(filled.right(), bar.center().y()), 7, 7)

    def paint_live(self, painter: QtGui.QPainter, activity: Live) -> None:
        """An activity card: its glyph, its reading, and its Stop circle."""
        lettering, bounds = self.capsule.look.lettering, QtCore.QRectF(self.rect())
        ink, quiet = color(lettering.ink), color(lettering.quiet)
        middle = bounds.height() / 2
        if activity.stop is island_menu.Command.STOP_RECORDING:
            painter.setBrush(QtGui.QColor(RED) if not self.capsule.contrast else ink)
            painter.drawEllipse(QtCore.QPointF(20, middle), 5, 5)
        else:
            self.capsule.paint_spinner(painter, Spot(Spinner(activity.label), 13, 14), middle)
        painter.setFont(font(strong=True))
        painter.setPen(ink)
        painter.drawText(
            QtCore.QRectF(40, 0, bounds.width() - 80, middle + 1), Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignLeft, activity.label
        )
        painter.setFont(caption_font())
        painter.setPen(quiet)
        detail = QtGui.QFontMetricsF(caption_font()).elidedText(activity.detail, Qt.TextElideMode.ElideRight, bounds.width() - 84)
        painter.drawText(QtCore.QRectF(40, middle, bounds.width() - 80, middle), Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft, detail)
        circle = self.stop_circle()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color(lettering.press if self.isDown() else lettering.hover))
        painter.drawEllipse(circle)
        painter.setOpacity(lettering.ink.opacity)
        icon("stop", lettering.ink.color).paint(painter, circle.adjusted(6, 6, -6, -6).toRect())

    def paint_tray(self, painter: QtGui.QPainter, slot: int, bounds: QtCore.QRectF) -> None:
        """The application's own image, one image pixel per screen pixel up to 22 px, on whole device pixels.

        Windows asks applications for tray icons at its small-icon size for the
        screen's scale, so drawing them unscaled keeps them as sharp as the taskbar.
        One without an image reads as a window.
        """
        images = self.capsule.window_.tray_images
        image = images[slot] if slot < len(images) else None
        if image is None:
            self.paint_icon(painter, "window", color(self.capsule.look.lettering.ink), bounds.center() - QtCore.QPointF(8, 8))
            return
        scale = self.devicePixelRatioF()
        side = min(22.0, image.width() / scale)
        left = round((bounds.center().x() - side / 2) * scale) / scale
        top = round((bounds.center().y() - side / 2) * scale) / scale
        painter.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawPixmap(QtCore.QRectF(left, top, side, side), image, QtCore.QRectF(image.rect()))

    def paint_icon(self, painter: QtGui.QPainter, name: str, ink: QtGui.QColor, at: QtCore.QPointF) -> None:
        painter.save()
        painter.setOpacity(ink.alphaF())
        icon(name, ink.name()).paint(painter, QtCore.QRect(round(at.x()), round(at.y()), 16, 16))
        painter.restore()


class Capsule(KeyboardFocus):
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
        self.cells: tuple[MenuCell, ...] = ()
        self.request: RequestPanel | None = None
        self.placed: tuple[QtCore.QRect, float, float, Content, tuple[Tile, ...]] | None = None
        self.stills: frozendict[tuple[Content, Look, bool, float], QtGui.QPixmap] = frozendict()
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.clicked.connect(self.pressed_capsule)

    def press(self, action: Action) -> None:
        self.window_.owner.press(action)

    def pressed_capsule(self) -> None:
        if self.view is not None:
            self.press(self.view.action)

    def show_view(self, drawn: Drawn, *, contrast: bool) -> None:
        state = (drawn.view, drawn.content, drawn.previous, drawn.fade, drawn.look, drawn.framed.presence, contrast)
        if (self.view, self.content, self.previous, self.fade, self.look, self.presence, self.contrast) == state:
            return
        if self.view is None or self.view.label != drawn.view.label:
            # Each change raises an accessibility event; frames of a fade keep the label.
            self.setToolTip("" if drawn.view.action is Action.CLOSE_MENU else drawn.view.label)
            self.setAccessibleName(drawn.view.label)
        self.view, self.content, self.previous, self.fade, self.look, self.presence, self.contrast = state
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
        laid = tiles(menu) if menu is not None else ()
        if len(laid) != len(self.cells) or any(cell.tile.cell.entry != tile.cell.entry for cell, tile in zip(self.cells, laid, strict=False)):
            for cell in self.cells:
                cell.hide()
                cell.deleteLater()
            self.cells = tuple(MenuCell(self, tile) for tile in laid)
        for cell, tile in zip(self.cells, laid, strict=True):
            cell.update_tile(tile)
            cell.update()

    def show_request(self, phase: Phase | None) -> None:
        if phase is None:
            if self.request is not None:
                self.request.hide()
            return
        actions = self.window_.owner.request_actions()
        if actions is None:
            return
        if self.request is None:
            self.request = RequestPanel(self, actions)
        self.request.present(phase, self.look)
        self.request.show()

    def place_cells(self) -> None:
        left = (self.width() - MENU_WIDTH) / 2
        for cell in self.cells:
            tile = cell.tile
            cell.setGeometry(round(left + tile.x), TOP + round(tile.y), round(tile.width), round(tile.height))
            cell.setVisible(TOP + tile.y + tile.height <= self.height())

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
        geometry = QtCore.QRect(round(framed.box.x), 0, max(1, round(framed.box.width)), TOP + round(framed.box.height))
        placed = (geometry, self.fade, self.presence, self.content, tuple(cell.tile for cell in self.cells))
        if placed == self.placed:
            return
        self.placed = placed
        self.setGeometry(geometry)
        self.place_controls()
        self.place_cells()
        if self.request is not None and self.request.isVisible():
            self.request.setGeometry(
                round((self.width() - desktop_ui.request_panel.WIDTH) / 2),
                TOP + MENU_HEAD,
                desktop_ui.request_panel.WIDTH,
                max(0, self.height() - TOP - MENU_HEAD),
            )
            self.request.setEnabled(
                self.width() >= desktop_ui.request_panel.WIDTH - 1 and self.request.height() >= self.request.measure(self.request.phase)
                if self.request.phase is not None
                else False
            )

    def update_indicators(self) -> None:
        """Repaint only the live indicators (spinner, dots, trace); the rest of the capsule is unchanged."""
        shift = self.shift(self.content)
        for spot in self.content.spots:
            if animated(spot.part):
                self.update(QtCore.QRect(math.floor(shift + spot.x) - 2, TOP, math.ceil(spot.width) + 4, HEIGHT))
        for cell in self.cells:
            match cell.tile.cell.entry:
                case Live(stop=island_menu.Command.STOP_AGENT):
                    cell.update(QtCore.QRect(11, cell.height() // 2 - 9, 18, 18))
                case _:
                    pass

    def enterEvent(self, event: QtGui.QEnterEvent) -> None:
        super().enterEvent(event)
        self.window_.owner.hover(self.key)
        self.update()

    def leaveEvent(self, event: QtCore.QEvent) -> None:
        super().leaveEvent(event)
        self.window_.owner.hover(None)
        self.update()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        shape = QtCore.QRectF(0, TOP, self.width(), self.height() - TOP)
        corner = min(radius(shape.height()), shape.height() / 2)
        outline = QtGui.QPainterPath()
        outline.addRoundedRect(shape, corner, corner)
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
        expanded = self.content.height > HEIGHT
        if (self.isDown() or self.underMouse()) and not expanded:
            painter.fillPath(outline, color(lettering.press if self.isDown() else lettering.hover))
        if self.hasFocus() and self.ringed:
            painter.setPen(QtGui.QPen(color(lettering.ink), 1.5))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(shape.adjusted(1.5, 1.5, -1.5, -1.5), corner - 1.5, corner - 1.5)
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
            painter.drawPixmap(QtCore.QPointF(0, 0), self.still(content))
            for spot in content.spots:
                if animated(spot.part):
                    self.paint_part(painter, spot, None, TOP + HEIGHT / 2)
            if content.height > HEIGHT and not content.spots:
                self.paint_heading(painter)  # An expanded capsule's own row replaces the heading.
            painter.restore()

    def still(self, content: Content) -> QtGui.QPixmap:
        """The content's unmoving parts, rendered once: a morphing capsule blits them each frame."""
        key = (content, self.look, self.contrast, self.devicePixelRatioF())
        cached = self.stills.get(key)
        if cached is not None:
            return cached
        scale = self.devicePixelRatioF()
        image = QtGui.QPixmap(max(1, math.ceil(content.width * scale)), math.ceil((TOP + HEIGHT) * scale))
        image.setDevicePixelRatio(scale)
        image.fill(Qt.GlobalColor.transparent)
        painter = QtGui.QPainter(image)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        previous: Spot | None = None
        for spot in content.spots:
            if not animated(spot.part):
                self.paint_part(painter, spot, previous, TOP + HEIGHT / 2)
            previous = spot
        painter.end()
        # Only the content showing now and the content fading out are kept.
        kept = {(c, self.look, self.contrast, scale) for c in (self.content, self.previous) if c is not None}
        self.stills = frozendict({**{k: v for k, v in self.stills.items() if k in kept}, key: image})
        return image

    def paint_heading(self, painter: QtGui.QPainter) -> None:
        heading = QtCore.QRectF(MENU_PAD + 10, TOP + MENU_PAD, MENU_WIDTH - 2 * MENU_PAD - 20, MENU_HEAD)
        painter.setFont(heading_font())
        painter.setPen(color(self.look.lettering.ink))
        painter.drawText(heading, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, "Workspace")

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
                trace = color(reading(lettering, Tone.INK, contrast=self.contrast))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(trace)
                for index, sample in enumerate(self.window_.trace()):
                    height = 3 + sample * 13
                    painter.drawRoundedRect(QtCore.QRectF(spot.x + index * 4, middle - height / 2, 2, height), 1, 1)
            case Marker.DOTS:
                self.paint_dots(painter, spot, middle)
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

    def paint_dots(self, painter: QtGui.QPainter, spot: Spot, middle: float) -> None:
        """A quick job: three dots pulsing in turn, distinct from the agent's ring."""
        ink = self.look.lettering.ink
        cycle = (90 - self.window_.spin_angle) % 360 / 360  # One turn of the frame clock per pulse cycle.
        painter.setPen(Qt.PenStyle.NoPen)
        for index in range(3):
            lift = max(0.0, math.sin((cycle - index / 6) * 2 * math.pi))
            painter.setBrush(color(Shade(ink.color, ink.opacity * (0.35 + 0.65 * lift))))
            painter.drawEllipse(QtCore.QPointF(spot.x + 3 + index * 6, middle - lift * 1.5), 2.2, 2.2)

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

    def __init__(self, loop: EventLoop, owner: Owner) -> None:
        super().__init__()
        self.loop = loop
        self.owner = owner
        self.menu: Menu | None = None
        self.request: Phase | None = None
        self.request_measurement: RequestPanel | None = None
        self.look: Look = look(Material.SOLID, appearance.Capsule(Frost.SMOKED), Tint.NONE)
        self.capsules: Mapping[Key, Capsule] = frozendict()
        self.spin_angle = 90.0
        # Qt owns the painted trace; samples arrive from the bar's audio meter.
        self.samples: deque[float] = deque([0.0] * WAVE_BARS, maxlen=WAVE_BARS)
        self.wave_from: tuple[float, ...] = tuple(self.samples)
        self.wave_progress = 1.0
        # This UI owner retains the immutable last application frame to avoid
        # native layout and glass work for unchanged indicator-only redraws.
        self.presentation: tuple[Presented, tuple[int, int, int, int], float] | None = None
        self.scene: GlassScene | None = None
        self.panes: tuple[Pane, ...] = ()
        self.shell_sections = ShellSections(self)
        # The bar's latest tray snapshot and Qt copies of its images, for the menu's tray cells.
        self.tray: tuple[Entry, ...] = ()
        self.tray_images: tuple[QtGui.QPixmap | None, ...] = ()
        self.glass = False
        self.setWindowTitle(BAR_WINDOW)
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
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
            left, top = outer.left + round(point.x() * scale), outer.top + round(point.y() * scale)
            return (Located(self.tray[slot], Rect(left, top, left + round(cell.width() * scale), top + round(cell.height() * scale))),)

        def slot(cell: MenuCell) -> tuple[Located, ...]:
            match cell.tile.cell.entry:
                case TrayIcon(slot=index):
                    return located(cell, index)
                case _:
                    return ()

        return tuple(found for cell in status.cells for found in slot(cell))

    def measure(self, view: CapsuleView) -> Content:
        def width(text: Text) -> float:
            return math.ceil(QtGui.QFontMetricsF(font(strong=text.strong)).horizontalAdvance(text.text))

        return arrange(view.slots, width)

    def measure_request(self, phase: Phase) -> Content:
        actions = self.owner.request_actions()
        if actions is None:
            return Content(desktop_ui.request_panel.WIDTH, (), 120)
        if self.request_measurement is None:
            self.request_measurement = RequestPanel(self, actions)
            self.request_measurement.hide()
        return Content(desktop_ui.request_panel.WIDTH, (), MENU_HEAD + self.request_measurement.measure(phase))

    def capsule(self, key: Key) -> Capsule:
        existing = self.capsules.get(key)
        if existing is not None:
            return existing
        created = Capsule(self, key)
        self.capsules = frozendict({**self.capsules, key: created})
        return created

    @override
    def wheelEvent(self, event: QtGui.QWheelEvent) -> None:
        """A horizontal scroll over any capsule swipes between desktops; Shift turns the vertical wheel sideways."""
        delta = event.angleDelta()
        sideways = delta.x() or (delta.y() if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 0)
        if sideways:
            self.owner.scroll(sideways)
        event.accept()

    def present(self, presented: Presented) -> None:
        """Show exactly these capsules where their frames put them; other pooled capsules hide."""
        area = QtGui.QGuiApplication.primaryScreen().geometry()
        scale = self.devicePixelRatioF()
        publication = (presented, (area.x(), area.y(), area.width(), area.height()), scale)
        if publication == self.presentation:
            return
        height = TOP + math.ceil(presented.height)
        if self.geometry() != QtCore.QRect(area.x(), area.y(), area.width(), height):
            self.setGeometry(area.x(), area.y(), area.width(), height)
        self.menu = presented.menu
        self.request = presented.request
        keys = frozenset(each.view.key for each in presented.drawn)
        for each in presented.drawn:
            capsule = self.capsule(each.view.key)
            capsule.show_view(each, contrast=presented.contrast)
            if each.view.key is Key.STATUS:
                capsule.show_menu(presented.menu if each.content.height > HEIGHT else None)
            if each.view.key is Key.ISLAND:
                capsule.show_request(presented.request if each.content.height > HEIGHT else None)
            capsule.frame(each.framed)
            capsule.show()
        for key, capsule in self.capsules.items():
            if key not in keys:
                capsule.hide()
        self.shell_sections.place(
            math.floor(min((each.framed.box.x for each in presented.drawn if each.view.key is not Key.CANVAS), default=area.width() / 2)),
            area.width(),
            start=next((round(each.framed.box.x + each.framed.box.width) + 6 for each in presented.drawn if each.view.key is Key.CANVAS), 12),
        )
        for section in self.shell_sections.sections():
            section.apply_look(presented.shell_look)
        self.glass = presented.glass
        self.panes = tuple(found for each in presented.drawn if (found := pane(each, presented.frost, scale)) is not None)
        match presented.shell_look:
            case GlassLook() as shell_look:
                self.panes = (
                    *self.panes,
                    *(
                        Pane(
                            key,
                            Rect(
                                round(section.x() * scale),
                                round(section.y() * scale),
                                round((section.x() + section.width()) * scale),
                                round((section.y() + section.height()) * scale),
                            ),
                            RADIUS * scale,
                            1,
                            _veil(shell_look, presented.frost),
                        )
                        for key, section in (
                            ("pinned applications", self.shell_sections.pinned),
                            ("desktops", self.shell_sections.pager),
                            ("applications", self.shell_sections.apps),
                        )
                        if section.isVisibleTo(self)
                    ),
                )
            case SolidLook():
                pass
        if not self.glass_timer.isActive():
            self.glass_timer.start(0)
        self.presentation = publication

    def trace(self) -> Iterator[float]:
        """Interpolate the displayed history between the meter's 50 ms samples."""
        progress = self.wave_progress
        return (before + (after - before) * progress for before, after in zip(self.wave_from, self.samples, strict=True))

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
        if self.request is not None and event.key() == Qt.Key.Key_Escape:
            self.owner.press(Action.CLOSE_MENU)
            return
        if self.menu is None:
            super().keyPressEvent(event)
            return
        named = keys.get(Qt.Key(event.key()))
        if named is not None:
            self.owner.key(named)
        elif event.text().isalpha():
            self.owner.key(island_menu.Letter(event.text()[0]))
        else:
            super().keyPressEvent(event)

    @override
    def changeEvent(self, event: QtCore.QEvent) -> None:
        super().changeEvent(event)
        if event.type() is QtCore.QEvent.Type.ActivationChange:
            if self.isActiveWindow():
                self.deactivation_timer.stop()
            elif (self.menu is not None or self.request is not None) and not self.deactivation_timer.isActive():
                self.deactivation_timer.start(16)

    def dismiss_inactive(self) -> None:
        if (self.menu is not None or self.request is not None) and not self.isActiveWindow():
            self.owner.deactivated()

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
        self.deactivation_timer.stop()
        self.menu = None
        self.hide()
        if self.scene is not None:
            self.scene.close()
            self.scene = None
        self.deleteLater()


def shifted(bounds: Rect, margin: int) -> Rect:
    return Rect(bounds.left + margin, bounds.top, bounds.right + margin, bounds.bottom)
