import math
from collections import deque
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field, replace
from functools import lru_cache
from typing import Final, assert_never, override

lazy from PySide6 import QtCore, QtGui, QtWidgets
lazy from PySide6.QtCore import Qt

from desktop_ui import island_menu
from desktop_ui.bar_control import Feedback, KeyboardFocus, paint_feedback
from desktop_ui.bar_events import (
    BarSpec,
    Deactivated,
    Event,
    Hovered,
    MenuKey,
    Paged,
    PanelPressed,
    Picked,
    Pressed,
    Selected,
    TrayClicked,
    VolumeSet,
)
from desktop_ui.components.appearance import (
    Glass,
    GlassLook,
    Look,
    Shade,
    SolidLook,
    reading,
    rim_stops,
)
from desktop_ui.components.meaning import Tone
from desktop_ui.components.text import color, hit, inter, outline, paint_capsule
from desktop_ui.components.typeface import Font
from desktop_ui.components.widgets import tool_window
from desktop_ui.island_layout import (
    Box,
    Cells,
    Content,
    Framed,
    Gauge,
    Sizes,
    Spot,
    Tile,
    arrange,
    fitted,
    lit,
    on_pixels,
    plotted,
    reading_at,
    tiles,
)
from desktop_ui.island_menu import (
    Calendar,
    Face,
    Fact,
    Graph,
    Item,
    Live,
    Menu,
    MenuWords,
    Nearby,
    Ranking,
    Slider,
    Toggle,
    TrayIcon,
)
from desktop_ui.island_model import (
    Action,
    CapsuleView,
    Charge,
    Control,
    Glyph,
    Key,
    Marker,
    Part,
    Text,
    Zone,
)
from desktop_ui.island_motion import Timing
from desktop_ui.live_marks import Beat, paint_dots, paint_wave
from desktop_ui.month import WEEKS, weeks
from desktop_ui.qt_runtime import prepare
from desktop_ui.shell_surface import Pager, pixmap
from desktop_ui.vector_icons import paint_icon
from winapi import appearance, windows
from winapi.appearance import Frost
from winapi.composition import DesktopComposition, GlassScene, borderless
from winapi.machine_status import Speakers
from winapi.shapes import Pane, Rect, Veil
from winapi.tray_host import Click, Entry, Located

prepare()


@dataclass(frozen=True, slots=True)
class Drawn:
    view: CapsuleView
    content: Content
    previous: Content | None
    fade: float
    look: Look
    framed: Framed


@dataclass(frozen=True, slots=True)
class Presented:
    drawn: tuple[Drawn, ...]
    height: float
    opened: Menu | None
    screen: Rect
    scale: float
    frost: Frost = field(kw_only=True)
    contrast: bool = field(kw_only=True)
    glass: bool = field(kw_only=True)
    shell_look: Look = field(kw_only=True)


def advance(text: str, font: Font) -> float:
    return math.ceil(QtGui.QFontMetricsF(inter(font)).horizontalAdvance(text))


def radius(height: float, sizes: Sizes) -> float:
    return sizes.menu.radius if expanded(height, sizes) else sizes.bar.radius


def expanded(height: float, sizes: Sizes) -> bool:
    return height > sizes.capsule.height + 0.5


def visibility(presence: float, timing: Timing) -> float:
    return min(1.0, max(0.0, presence / timing.opaque_at))


def animated(part: Part) -> bool:
    match part:
        case Marker.DOTS | Marker.WAVE:
            return True
        case _:
            return False


def controls(content: Content) -> tuple[tuple[Control, float], ...]:

    def control(spot: Spot) -> tuple[tuple[Control, float], ...]:
        match spot.part:
            case Control() as part:
                return ((part, spot.x),)
            case _:
                return ()

    return tuple(found for spot in content.spots for found in control(spot))


@lru_cache(maxsize=32)
def _veil(look: GlassLook, frost: Frost, glass: Glass) -> Veil:
    return Veil(
        look.veil.color,
        look.veil.opacity,
        rim_stops(look.rim, glass),
        glass.frosts[frost].shadow,
    )


def pane(drawn: Drawn, presented: Presented, spec: BarSpec) -> Pane | None:
    match drawn.look:
        case GlassLook() as look:
            box = drawn.framed.box
            return Pane(
                drawn.view.key.name,
                box.on_device(presented.scale),
                min(radius(drawn.content.height, spec.sizes), box.height / 2)
                * presented.scale,
                visibility(drawn.framed.presence, spec.timing),
                _veil(look, presented.frost, spec.glass),
            )
        case SolidLook():
            return None
        case _:
            assert_never(drawn.look)


class ControlButton(KeyboardFocus):
    def __init__(self, capsule: Capsule, control: Control) -> None:
        super().__init__(capsule)
        self.capsule = capsule
        self.control = control
        side = round(capsule.window_.sizes.capsule.control)
        self.setFixedSize(side, side)
        self.setToolTip(control.label)
        self.setAccessibleName(control.label)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.clicked.connect(self.pressed_control)

    def update_control(self, control: Control) -> None:
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
        self.paint_round(painter, lettering)
        symbol = round(self.capsule.window_.sizes.capsule.icon)
        inset = (self.width() - symbol) // 2
        paint_icon(
            painter,
            self.control.icon,
            lettering.ink,
            QtCore.QRect(inset, inset, symbol, symbol),
        )


def track(bounds: QtCore.QRectF, cells: Cells) -> QtCore.QRectF:
    return QtCore.QRectF(
        cells.text_x,
        bounds.height() - cells.track_bottom,
        bounds.width() - cells.text_x - cells.track_right,
        cells.track,
    )


def sound_reading(slider: Slider, words: MenuWords) -> str:
    if slider.level is None:
        return words.unread
    return f"{round(slider.level * 100)}%" + (
        f", {words.muted}" if slider.muted else ""
    )


class MenuCell(QtWidgets.QAbstractButton):
    def __init__(self, capsule: Capsule, tile: Tile) -> None:
        super().__init__(capsule)
        self.capsule = capsule
        self.tile = tile
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.clicked.connect(self.picked)
        self.describe()

    def describe(self) -> None:
        match self.tile.cell.entry:
            case Live(label=label, detail=detail):
                name = " · ".join(
                    part
                    for part in (
                        label,
                        detail,
                        self.capsule.window_.spec.island.words.stop_recording,
                    )
                    if part
                )
            case Item(label=label, key=key):
                name = f"{label} · {key}" if key else label
            case Toggle(label=label, detail=detail):
                name = f"{label}: {detail}"
            case Slider(label=label) as slider:
                name = f"{label}: {sound_reading(slider, self.capsule.window_.spec.controls.words)}"
            case TrayIcon(label=label):
                name = label
            case Calendar(label=label, month=month):
                name = f"{label}: {month.first().strftime(self.capsule.window_.spec.controls.words.month)}"
            case Graph(label=label, trace=trace):
                name = f"{label}: {trace.reading}"
            case Ranking(label=label, rows=rows):
                listed = ", ".join(f"{row.name} {row.reading}" for row in rows)
                name = f"{label}: {listed}"
            case Nearby(label=label, detail=detail):
                name = f"{label}: {detail}"
            case Fact(label=label, value=value, detail=detail):
                name = ", ".join(
                    part for part in (f"{label}: {value}", detail) if part
                )
            case _:
                assert_never(self.tile.cell.entry)
        if self.accessibleName() != name:
            self.setAccessibleName(name)
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

    @property
    def sizes(self) -> Sizes:
        return self.capsule.window_.sizes

    def stop_circle(self) -> QtCore.QRectF:
        control = self.sizes.capsule.control
        return QtCore.QRectF(
            self.width() - control - self.sizes.cells.stop_right,
            (self.height() - control) / 2,
            control,
            control,
        )

    def month_heading(
        self,
    ) -> tuple[QtCore.QRectF, QtCore.QRectF, QtCore.QRectF]:
        cells = self.sizes.cells
        later = QtCore.QRectF(
            self.width() - cells.month_side - cells.month_arrow,
            0,
            cells.month_arrow,
            cells.month_head,
        )
        earlier = later.translated(-cells.month_arrow, 0)
        return (
            QtCore.QRectF(
                cells.lead, 0, earlier.left() - cells.lead, cells.month_head
            ),
            earlier,
            later,
        )

    @override
    def hitButton(self, pos: QtCore.QPoint) -> bool:
        match self.tile.cell.entry:
            case Live():
                return self.stop_circle().contains(QtCore.QPointF(pos))
            case Slider() | Calendar() | Graph() | Ranking() | Fact():
                return False  # The slider and the calendar take the pointer themselves rather than clicking.
            case Item() | Toggle() | TrayIcon() | Nearby():
                return super().hitButton(pos)
            case _:
                assert_never(self.tile.cell.entry)

    def slide(self, pos: QtCore.QPointF) -> None:
        match self.tile.cell.entry:
            case Slider(level=float()):
                bar = track(QtCore.QRectF(self.rect()), self.sizes.cells)
                self.capsule.window_.report(
                    VolumeSet(
                        round(
                            min(
                                1.0,
                                max(0.0, (pos.x() - bar.left()) / bar.width()),
                            ),
                            2,
                        )
                    )
                )
            case _:
                pass

    def turn(self, pos: QtCore.QPointF) -> None:
        match self.tile.cell.entry:
            case Calendar():
                heading, earlier, later = self.month_heading()
                if earlier.contains(pos):
                    self.capsule.window_.report(Paged(-1))
                elif later.contains(pos):
                    self.capsule.window_.report(Paged(1))
                elif heading.contains(pos):
                    self.capsule.window_.report(Picked(self.tile.index))
            case _:
                pass

    @override
    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        super().mousePressEvent(event)
        self.slide(event.position())
        self.turn(event.position())
        event.accept()

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
            case TrayIcon(slot=slot) if (
                event.button() is Qt.MouseButton.RightButton
                and self.rect().contains(event.position().toPoint())
            ):
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
        cells, icon = self.sizes.cells, self.sizes.capsule.icon
        corner = bounds.height() / 2 if cell.face is Face.LINK else cells.corner
        painter.setPen(Qt.PenStyle.NoPen)
        if cell.face is not Face.LINK:
            painter.setBrush(
                color(
                    Shade(lettering.ink.color, self.capsule.window_.washes.well)
                )
            )
            painter.drawRoundedRect(bounds, corner, corner)
        still = cell.face in (
            Face.CARD,
            Face.CALENDAR,
            Face.GRAPH,
            Face.RANKING,
            Face.FACT,
        )  # Nothing to press but a part of it.
        paint_feedback(
            painter,
            lettering,
            bounds,
            corner,
            Feedback(pressed=chosen, hovered=self.underMouse() and not still),
        )
        match cell.entry:
            case Live() as activity:
                self.paint_live(painter, activity)
            case Toggle() as toggle:
                self.paint_toggle(painter, toggle)
            case Slider() as slider:
                self.paint_slider(painter, slider)
            case Item(icon=name) if cell.face is Face.TOOL:
                self.paint_icon(
                    painter,
                    name,
                    lettering.ink,
                    QtCore.QPointF((bounds.width() - icon) / 2, cells.tool_top),
                )
                painter.setPen(color(lettering.quiet))
                painter.setFont(inter(self.sizes.type.detail))
                caption = bounds.adjusted(
                    cells.caption_side,
                    0,
                    -cells.caption_side,
                    -cells.caption_bottom,
                )
                painter.drawText(
                    caption,
                    Qt.AlignmentFlag.AlignBottom
                    | Qt.AlignmentFlag.AlignHCenter,
                    cell.caption,
                )
            case Item(label=label, icon=name, key=key):
                self.paint_icon(
                    painter,
                    name,
                    lettering.quiet,
                    QtCore.QPointF(cells.lead, (bounds.height() - icon) / 2),
                )
                painter.setFont(inter(self.sizes.type.reading))
                painter.setPen(color(lettering.ink))
                labelled = bounds.adjusted(
                    cells.label_x, 0, -cells.label_right, 0
                )
                painter.drawText(
                    labelled,
                    Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                    label,
                )
                if key:
                    painter.setPen(color(lettering.quiet))
                    painter.drawText(
                        bounds.adjusted(0, 0, -cells.trail, 0),
                        Qt.AlignmentFlag.AlignVCenter
                        | Qt.AlignmentFlag.AlignRight,
                        key,
                    )
            case TrayIcon(slot=slot):
                self.paint_tray(painter, slot, bounds)
            case Calendar() as month:
                self.paint_month(painter, month)
            case Graph() as graph:
                self.paint_graph(painter, graph)
            case Ranking() as ranking:
                self.paint_ranking(painter, ranking)
            case Nearby() as nearby:
                self.paint_network(painter, nearby)
            case Fact() as fact:
                self.paint_fact(painter, fact, bounds)
            case _:
                assert_never(cell.entry)

    def paint_fact(
        self, painter: QtGui.QPainter, fact: Fact, bounds: QtCore.QRectF
    ) -> None:
        """The fact's symbol beside its value over what it means."""
        cells = self.sizes.cells
        self.paint_symbol(painter, fact.icon, on=False)
        area = QtCore.QRectF(
            cells.text_x,
            0,
            bounds.width() - cells.text_x - cells.text_right,
            bounds.height(),
        )
        self.paint_lines(painter, area, fact.value, fact.detail, strong=True)

    def paint_symbol(
        self, painter: QtGui.QPainter, name: str, *, on: bool
    ) -> None:
        lettering = self.capsule.drawn.look.lettering
        capsule = self.sizes.capsule
        at = QtCore.QPointF(
            self.sizes.cells.symbol_x, (self.height() - capsule.control) / 2
        )
        painter.setPen(Qt.PenStyle.NoPen)
        off = Shade(lettering.ink.color, self.capsule.window_.washes.off)
        painter.setBrush(
            color(
                self.capsule.signal(
                    self.capsule.window_.spec.palette.accent, lettering.ink
                )
                if on
                else off
            )
        )
        painter.drawEllipse(
            QtCore.QRectF(at.x(), at.y(), capsule.control, capsule.control)
        )
        ink = (
            self.capsule.signal(
                self.capsule.window_.spec.palette.on_accent, lettering.press
            )
            if on
            else lettering.ink
        )
        inset = (capsule.control - capsule.icon) / 2
        self.paint_icon(
            painter, name, ink, QtCore.QPointF(at.x() + inset, at.y() + inset)
        )

    def paint_toggle(self, painter: QtGui.QPainter, toggle: Toggle) -> None:
        self.paint_symbol(painter, toggle.icon, on=toggle.on)
        cells = self.sizes.cells
        area = QtCore.QRectF(
            cells.text_x,
            0,
            self.width() - cells.text_x - cells.text_right,
            self.height(),
        )
        self.paint_lines(
            painter, area, toggle.label, toggle.detail, strong=False
        )

    def paint_lines(
        self,
        painter: QtGui.QPainter,
        area: QtCore.QRectF,
        title: str,
        detail: str,
        *,
        strong: bool,
    ) -> None:
        lettering, middle = self.capsule.drawn.look.lettering, area.height() / 2
        text = self.sizes.type
        painter.setFont(inter(text.strong if strong else text.reading))
        painter.setPen(color(lettering.ink))
        painter.drawText(
            QtCore.QRectF(area.left(), 0, area.width(), middle + 1),
            Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignLeft,
            title,
        )
        painter.setFont(inter(text.detail))
        painter.setPen(color(lettering.quiet))
        painter.drawText(
            QtCore.QRectF(area.left(), middle, area.width(), middle),
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft,
            detail,
        )

    def paint_slider(self, painter: QtGui.QPainter, slider: Slider) -> None:
        lettering, bounds, cells = (
            self.capsule.drawn.look.lettering,
            QtCore.QRectF(self.rect()),
            self.sizes.cells,
        )
        painter.setFont(inter(self.sizes.type.strong))
        painter.setPen(color(lettering.ink))
        heading = QtCore.QRectF(
            cells.lead,
            cells.slider_label_top,
            bounds.width() - 2 * cells.lead,
            cells.slider_label,
        )
        painter.drawText(
            heading,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            slider.label,
        )
        bar = track(bounds, cells)
        speakers = self.capsule.window_.spec.island.status.speakers
        symbol = speakers[
            Speakers.MUTED if slider.muted else Speakers.AUDIBLE
        ].icon
        self.paint_icon(
            painter,
            symbol,
            lettering.quiet,
            QtCore.QPointF(
                cells.lead, bar.center().y() - self.sizes.capsule.icon / 2
            ),
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(
            color(Shade(lettering.ink.color, self.capsule.window_.washes.track))
        )
        painter.drawRoundedRect(bar, cells.track_corner, cells.track_corner)
        if slider.level is None:
            return
        filled = QtCore.QRectF(
            bar.left(), bar.top(), bar.width() * slider.level, bar.height()
        )
        painter.setBrush(
            color(
                lettering.quiet
                if slider.muted
                else self.capsule.signal(
                    self.capsule.window_.spec.palette.accent, lettering.ink
                )
            )
        )
        painter.drawRoundedRect(filled, cells.track_corner, cells.track_corner)
        painter.setBrush(
            color(
                self.capsule.signal(
                    self.capsule.window_.spec.palette.on_accent, lettering.ink
                )
            )
        )
        painter.drawEllipse(
            QtCore.QPointF(filled.right(), bar.center().y()),
            cells.knob,
            cells.knob,
        )

    def paint_live(self, painter: QtGui.QPainter, activity: Live) -> None:
        lettering, bounds, cells = (
            self.capsule.drawn.look.lettering,
            QtCore.QRectF(self.rect()),
            self.sizes.cells,
        )
        paint_dot(
            painter,
            color(
                self.capsule.signal(
                    self.capsule.window_.spec.palette.red, lettering.ink
                )
            ),
            QtCore.QPointF(cells.live_dot_x, bounds.height() / 2),
            cells.live_dot,
        )
        detail = QtGui.QFontMetricsF(inter(self.sizes.type.detail)).elidedText(
            activity.detail,
            Qt.TextElideMode.ElideRight,
            bounds.width() - cells.live_elide,
        )
        area = QtCore.QRectF(
            cells.live_text_x,
            0,
            bounds.width() - cells.live_text_x - cells.live_text_right,
            bounds.height(),
        )
        self.paint_lines(painter, area, activity.label, detail, strong=True)
        circle = self.stop_circle()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(
            color(lettering.press if self.isDown() else lettering.hover)
        )
        painter.drawEllipse(circle)
        inset = (self.sizes.capsule.control - self.sizes.capsule.icon) / 2
        paint_icon(
            painter,
            "stop",
            lettering.ink,
            circle.adjusted(inset, inset, -inset, -inset).toRect(),
        )

    def paint_month(self, painter: QtGui.QPainter, shown: Calendar) -> None:
        lettering, cells, text = (
            self.capsule.drawn.look.lettering,
            self.sizes.cells,
            self.sizes.type,
        )
        spec = self.capsule.window_.spec
        heading, earlier, later = self.month_heading()
        centred = Qt.AlignmentFlag.AlignCenter
        painter.setFont(inter(text.strong))
        painter.setPen(color(lettering.ink))
        painter.drawText(
            heading,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            shown.month.first().strftime(spec.controls.words.month),
        )
        half = self.sizes.capsule.icon / 2
        for name, arrow in (("earlier", earlier), ("later", later)):
            self.paint_icon(
                painter,
                name,
                lettering.ink,
                arrow.center() - QtCore.QPointF(half, half),
            )
        shown_weeks = weeks(shown.month, spec.controls.first_weekday)
        column = (self.width() - 2 * cells.month_side) / 7
        top = cells.month_head + cells.weekdays
        row = (self.height() - top - cells.month_side) / WEEKS

        def box(across: int, line: float, height: float) -> QtCore.QRectF:
            return QtCore.QRectF(
                cells.month_side + across * column, line, column, height
            )

        painter.setFont(inter(text.detail))
        painter.setPen(color(lettering.quiet))
        for across, day in enumerate(shown_weeks[0]):
            painter.drawText(
                box(across, cells.month_head, cells.weekdays),
                centred,
                day.strftime(spec.controls.words.weekday),
            )
        painter.setFont(inter(text.reading))
        for down, week in enumerate(shown_weeks):
            for across, day in enumerate(week):
                place = box(across, top + down * row, row)
                if day == shown.today and self.capsule.contrast:
                    painter.setPen(color(lettering.ink))
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawEllipse(
                        place.center(), cells.today, cells.today
                    )
                elif day == shown.today:
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(color(Shade(spec.palette.accent)))
                    painter.drawEllipse(
                        place.center(), cells.today, cells.today
                    )
                    painter.setPen(color(Shade(spec.palette.on_accent)))
                else:
                    painter.setPen(
                        color(
                            lettering.ink
                            if day.month == shown.month.month
                            else lettering.quiet
                        )
                    )
                painter.drawText(place, centred, str(day.day))

    def paint_graph(self, painter: QtGui.QPainter, graph: Graph) -> None:
        lettering, cells, text = (
            self.capsule.drawn.look.lettering,
            self.sizes.cells,
            self.sizes.type,
        )
        spec, window = self.capsule.window_.spec, self.capsule.window_
        heading = QtCore.QRectF(
            cells.lead,
            0,
            self.width() - cells.lead - cells.trail,
            cells.graph_head,
        )
        painter.setFont(inter(text.strong))
        painter.setPen(color(lettering.ink))
        painter.drawText(
            heading,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            graph.label,
        )
        painter.setFont(inter(text.reading))
        painter.setPen(color(lettering.quiet))
        painter.drawText(
            heading,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
            graph.trace.reading,
        )
        box = Box(
            cells.lead,
            cells.graph_head,
            self.width() - cells.lead - cells.trail,
            self.height() - cells.graph_head - cells.lead,
        )
        hue = self.capsule.signal(spec.palette.accent, lettering.ink).color
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color(Shade(lettering.ink.color, window.washes.track)))
        painter.drawRect(
            QtCore.QRectF(
                box.x, box.y + box.height, box.width, cells.graph_line / 2
            )
        )
        for run in plotted(graph.trace.shares, graph.trace.capacity, box):
            line = QtGui.QPolygonF(
                [QtCore.QPointF(point.x, point.y) for point in run]
            )
            bottom = box.y + box.height
            area = QtGui.QPolygonF(line)
            area.append(QtCore.QPointF(line.last().x(), bottom))
            area.prepend(QtCore.QPointF(line.first().x(), bottom))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color(Shade(hue, window.washes.halo)))
            painter.drawPolygon(area)
            pen = QtGui.QPen(color(Shade(hue)), cells.graph_line)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPolyline(line)

    def paint_ranking(self, painter: QtGui.QPainter, ranking: Ranking) -> None:
        """The ranking's name over its apps: each app's name and reading, over a bar filled to its
        share in the graphs' accent."""
        lettering, cells, text = (
            self.capsule.drawn.look.lettering,
            self.sizes.cells,
            self.sizes.type,
        )
        spec, window = self.capsule.window_.spec, self.capsule.window_
        width = self.width() - cells.lead - cells.trail
        painter.setFont(inter(text.strong))
        painter.setPen(color(lettering.ink))
        painter.drawText(
            QtCore.QRectF(cells.lead, 0, width, cells.graph_head),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            ranking.label,
        )
        hue = self.capsule.signal(spec.palette.accent, lettering.ink).color
        track = color(Shade(lettering.ink.color, window.washes.track))
        filled = color(Shade(hue))
        painter.setFont(inter(text.reading))
        for place, row in enumerate(ranking.rows):
            top = cells.graph_head + place * cells.rank_row
            line = QtCore.QRectF(
                cells.lead, top, width, cells.rank_row - cells.rank_bar
            )
            painter.setPen(color(lettering.ink))
            painter.drawText(
                line,
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                row.name,
            )
            painter.setPen(color(lettering.quiet))
            painter.drawText(
                line,
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                row.reading,
            )
            bar = QtCore.QRectF(
                cells.lead, line.bottom(), width, cells.rank_bar
            )
            corner = cells.rank_bar / 2
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(track)
            painter.drawRoundedRect(bar, corner, corner)
            painter.setBrush(filled)
            painter.drawRoundedRect(
                QtCore.QRectF(
                    bar.left(),
                    bar.top(),
                    max(bar.height(), width * row.share),
                    bar.height(),
                ),
                corner,
                corner,
            )

    def paint_network(self, painter: QtGui.QPainter, nearby: Nearby) -> None:
        lettering, cells, icon = (
            self.capsule.drawn.look.lettering,
            self.sizes.cells,
            self.sizes.capsule.icon,
        )
        network, middle = nearby.network, self.height() / 2
        bars, step = 4, (icon - cells.signal_bar) / 3
        lit = math.ceil(network.signal * bars / 100)
        painter.setPen(Qt.PenStyle.NoPen)
        for bar in range(bars):
            tall = icon * (bar + 1) / bars
            painter.setBrush(
                color(
                    lettering.ink
                    if bar < lit
                    else Shade(
                        lettering.ink.color, self.capsule.window_.washes.track
                    )
                )
            )
            painter.drawRect(
                QtCore.QRectF(
                    cells.lead + bar * step,
                    middle + icon / 2 - tall,
                    cells.signal_bar,
                    tall,
                )
            )
        marks = (
            *(("lock",) if network.secured else ()),
            *(("check",) if network.connected else ()),
        )
        right = self.width() - cells.trail
        for index, mark in enumerate(reversed(marks)):
            self.paint_icon(
                painter,
                mark,
                lettering.quiet,
                QtCore.QPointF(
                    right - (index + 1) * icon - index * cells.signal_bar,
                    middle - icon / 2,
                ),
            )
        text = QtCore.QRectF(
            cells.label_x,
            0,
            right - cells.label_x - len(marks) * (icon + cells.signal_bar),
            self.height(),
        )
        title = QtGui.QFontMetricsF(inter(self.sizes.type.reading)).elidedText(
            network.ssid, Qt.TextElideMode.ElideRight, text.width()
        )
        self.paint_lines(
            painter, text, title, nearby.detail, strong=network.connected
        )

    def paint_tray(
        self, painter: QtGui.QPainter, slot: int, bounds: QtCore.QRectF
    ) -> None:
        images = self.capsule.window_.tray_images
        image = images[slot] if slot < len(images) else None
        if image is None:
            half = self.sizes.capsule.icon / 2
            self.paint_icon(
                painter,
                "window",
                self.capsule.drawn.look.lettering.ink,
                bounds.center() - QtCore.QPointF(half, half),
            )
            return
        scale = self.devicePixelRatioF()
        side = min(self.sizes.cells.tray_image, image.width() / scale)
        left, top = (
            on_pixels(bounds.center().x() - side / 2, scale),
            on_pixels(bounds.center().y() - side / 2, scale),
        )
        painter.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawPixmap(
            QtCore.QRectF(left, top, side, side),
            image,
            QtCore.QRectF(image.rect()),
        )

    def paint_icon(
        self, painter: QtGui.QPainter, name: str, ink: Shade, at: QtCore.QPointF
    ) -> None:
        side = round(self.sizes.capsule.icon)
        paint_icon(
            painter,
            name,
            ink,
            QtCore.QRect(round(at.x()), round(at.y()), side, side),
        )


@dataclass(frozen=True, slots=True)
class Lit:
    slot: int | None = None
    left: int | None = None


GLOW: Final = 160
"""Milliseconds a reading's pill takes to fade in or out."""


class Capsule(KeyboardFocus):
    def __init__(
        self, window: BarWindow, drawn: Drawn, *, contrast: bool
    ) -> None:
        super().__init__(window)
        self.window_ = window
        self.key = drawn.view.key
        self.drawn = drawn
        """The frame it shows: its view, content, any content fading out, how it reads and its presence."""
        self.contrast = contrast
        self.controls = tuple(
            ControlButton(self, control)
            for control, _ in controls(drawn.content)
        )
        self.cells: tuple[MenuCell, ...] = ()
        self.placed: (
            tuple[QtCore.QRect, float, float, Content, tuple[Tile, ...]] | None
        ) = None
        self.stills: frozendict[
            tuple[Content, Look, bool, float], QtGui.QPixmap
        ] = frozendict()
        self.lit = Lit()
        """Which reading lights under the pointer; a capsule without panels lights as a whole."""
        self.glow = QtCore.QVariantAnimation(self)
        self.glow.setDuration(GLOW)
        self.glow.setStartValue(0.0)
        self.glow.setEndValue(1.0)
        self.glow.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
        self.glow.valueChanged.connect(self.update)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.clicked.connect(self.pressed_capsule)
        self.describe(drawn.view)

    def press(self, action: Action) -> None:
        self.window_.report(Pressed(action))

    def signal(self, hue: str, ink: Shade) -> Shade:
        return ink if self.contrast else Shade(hue)

    def pressed_capsule(self) -> None:
        view = self.drawn.view
        if view.zone is Zone.PANEL:
            return
        pointer = self.mapFromGlobal(QtGui.QCursor.pos())
        slot = (
            self.reading_under(QtCore.QPointF(pointer))
            if self.rect().contains(pointer)
            else None
        )
        if slot is not None and slot < len(view.panels):
            self.window_.report(PanelPressed(view.panels[slot], slot))
            return
        self.press(view.action)

    def strip(self) -> float:
        return (
            0.0
            if self.drawn.view.zone is Zone.PANEL
            else self.window_.sizes.bar.top
        )

    def describe(self, view: CapsuleView) -> None:
        self.setToolTip(
            "" if view.action is Action.CLOSE_MENU or view.tips else view.label
        )
        self.setAccessibleName(view.label)

    @override
    def event(self, event: QtCore.QEvent) -> bool:
        view = self.drawn.view
        if event.type() is not QtCore.QEvent.Type.ToolTip or not view.tips:
            return super().event(event)
        assert isinstance(event, QtGui.QHelpEvent)
        sizes, content = self.window_.sizes, self.drawn.content
        slot = self.reading_under(QtCore.QPointF(event.pos()))
        box = (
            lit(content, slot, sizes.capsule)
            if slot is not None and slot < len(view.tips)
            else None
        )
        if view.action is Action.CLOSE_MENU or slot is None or box is None:
            QtWidgets.QToolTip.hideText()
            event.ignore()
            return True
        area = QtCore.QRectF(
            self.shift(content) + box.x,
            sizes.bar.top + box.y,
            box.width,
            box.height,
        ).toAlignedRect()
        QtWidgets.QToolTip.showText(
            event.globalPos(), view.tips[slot], self, area
        )
        return True

    def show_view(self, drawn: Drawn, *, contrast: bool) -> None:
        before, self.drawn = self.drawn, drawn
        if (
            contrast == self.contrast
            and replace(
                before, framed=replace(before.framed, box=drawn.framed.box)
            )
            == drawn
        ):
            return
        if before.view.label != drawn.view.label:
            self.describe(drawn.view)
        self.contrast = contrast
        wanted = controls(drawn.content)
        if tuple(button.control.action for button in self.controls) != tuple(
            control.action for control, _ in wanted
        ):
            for button in self.controls:
                button.hide()
                button.deleteLater()
            self.controls = tuple(
                ControlButton(self, control) for control, _ in wanted
            )
        for button, (control, _) in zip(self.controls, wanted, strict=True):
            button.update_control(control)
        self.update()

    def show_menu(self, menu: Menu | None) -> None:
        laid = (
            tiles(menu, self.window_.sizes.menu, self.window_.fit(menu))
            if menu is not None
            else ()
        )
        if len(laid) != len(self.cells) or any(
            cell.tile.cell.entry != tile.cell.entry
            for cell, tile in zip(self.cells, laid, strict=False)
        ):
            for cell in self.cells:
                cell.hide()
                cell.deleteLater()
            self.cells = tuple(MenuCell(self, tile) for tile in laid)
        for cell, tile in zip(self.cells, laid, strict=True):
            cell.update_tile(tile)
            cell.update()

    def place_cells(self) -> None:
        top = round(self.strip())
        left = self.shift(self.drawn.content)
        for cell in self.cells:
            tile = cell.tile
            cell.setGeometry(
                round(left + tile.x),
                top + round(tile.y),
                round(tile.width),
                round(tile.height),
            )
            cell.setVisible(top + tile.y + tile.height <= self.height())

    def place_controls(self) -> None:
        shift = self.shift(self.drawn.content)
        for button, (_, x) in zip(
            self.controls, controls(self.drawn.content), strict=True
        ):
            button.move(
                round(shift + x),
                round(
                    self.window_.sizes.bar.top
                    + self.window_.sizes.capsule.inset
                ),
            )
            button.setVisible(
                self.drawn.fade > 0.5
                and visibility(
                    self.drawn.framed.presence, self.window_.spec.timing
                )
                == 1
            )

    def shift(self, content: Content) -> float:
        return (self.width() - content.width) / 2

    def frame(self, framed: Framed) -> None:
        top = round(self.strip())
        geometry = QtCore.QRect(
            round(framed.box.x),
            round(framed.box.y) - top,
            max(1, round(framed.box.width)),
            top + round(framed.box.height),
        )
        placed = (
            geometry,
            self.drawn.fade,
            self.drawn.framed.presence,
            self.drawn.content,
            tuple(cell.tile for cell in self.cells),
        )
        if placed == self.placed:
            return
        self.placed = placed
        self.setGeometry(geometry)
        self.place_controls()
        self.place_cells()

    def update_indicators(self) -> None:
        shift, sizes = self.shift(self.drawn.content), self.window_.sizes
        for spot in self.drawn.content.spots:
            if animated(spot.part):
                self.update(
                    QtCore.QRect(
                        math.floor(shift + spot.x) - 2,
                        round(sizes.bar.top),
                        math.ceil(spot.width) + 4,
                        round(sizes.capsule.height),
                    )
                )

    @override
    def enterEvent(self, event: QtGui.QEnterEvent) -> None:
        super().enterEvent(event)
        self.window_.report(Hovered(self.key))
        self.light(self.reading_under(event.position()))
        self.update()

    @override
    def leaveEvent(self, event: QtCore.QEvent) -> None:
        super().leaveEvent(event)
        self.window_.report(Hovered(None))
        self.light(None)
        self.update()

    @override
    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
        super().mouseMoveEvent(event)
        self.light(self.reading_under(event.position()))

    def reading_under(self, pointer: QtCore.QPointF) -> int | None:
        sizes = self.window_.sizes
        if (
            not self.drawn.view.panels
            or pointer.y() > sizes.bar.top + sizes.capsule.height
        ):
            return None
        return reading_at(
            self.drawn.content, pointer.x() - self.shift(self.drawn.content)
        )

    def light(self, slot: int | None) -> None:
        if slot == self.lit.slot:
            return
        self.lit = Lit(slot, self.lit.slot)
        self.glow.stop()
        if appearance.animations_enabled():
            self.glow.start()
        else:
            self.glow.setCurrentTime(GLOW)
        self.update()

    def paint_lit(self, painter: QtGui.QPainter) -> None:
        lettering, sizes, content = (
            self.drawn.look.lettering,
            self.window_.sizes,
            self.drawn.content,
        )
        glow = self.glow.currentValue()
        rise = glow if isinstance(glow, float) else 1.0
        opened = self.window_.menu
        held = None
        if opened is not None:
            first = next(
                (
                    index
                    for index, panel in enumerate(self.drawn.view.panels)
                    if panel is opened.panel
                ),
                None,
            )
            held = opened.anchor if opened.anchor is not None else first
        pills = (
            (self.lit.left, 1 - rise, False),
            (self.lit.slot, rise, self.isDown()),
            (held, 1.0, True),
        )
        for slot, opacity, pressed in pills:
            if (
                slot is None
                or opacity <= 0
                or not (box := lit(content, slot, sizes.capsule))
            ):
                continue
            pill = QtCore.QRectF(
                self.shift(content) + box.x,
                sizes.bar.top + box.y,
                box.width,
                box.height,
            )
            painter.save()
            painter.setOpacity(opacity)
            paint_feedback(
                painter,
                lettering,
                pill,
                box.height / 2,
                Feedback(pressed=pressed, hovered=True),
            )
            painter.restore()

    @override
    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        sizes = self.window_.sizes
        top, middle = self.strip(), sizes.bar.top + sizes.capsule.height / 2
        shape = QtCore.QRectF(0, top, self.width(), self.height() - top)
        corner = min(
            radius(self.drawn.content.height, sizes), shape.height() / 2
        )
        path = outline(shape, corner)
        if top:
            strip = QtGui.QPainterPath()
            strip.addRect(QtCore.QRectF(0, 0, self.width(), top))
            painter.fillPath(strip, hit())
        alpha = visibility(self.drawn.framed.presence, self.window_.spec.timing)
        paint_capsule(painter, path, self.drawn.look, alpha)
        drawn = self.drawn
        whole = (
            not expanded(drawn.content.height, sizes) and not drawn.view.panels
        )
        paint_feedback(
            painter,
            drawn.look.lettering,
            shape,
            corner,
            Feedback(
                pressed=self.isDown() and whole,
                hovered=self.underMouse() and whole,
                ringed=self.focus_ringed,
                inset=sizes.capsule.ring_inset,
            ),
        )
        if drawn.view.panels:
            self.paint_lit(painter)
        painter.setClipPath(path)
        layers: tuple[tuple[Content, float], ...] = (
            (
                (drawn.previous, alpha * (1 - drawn.fade)),
                (drawn.content, alpha * drawn.fade),
            )
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
        key = (
            content,
            self.drawn.look,
            self.contrast,
            self.devicePixelRatioF(),
        )
        cached = self.stills.get(key)
        if cached is not None:
            return cached
        scale = self.devicePixelRatioF()
        top, row = self.window_.sizes.bar.top, self.window_.sizes.capsule.height
        image = QtGui.QPixmap(
            max(1, math.ceil(content.width * scale)),
            math.ceil((top + max(row, content.height)) * scale),
        )
        image.setDevicePixelRatio(scale)
        image.fill(Qt.GlobalColor.transparent)
        painter = QtGui.QPainter(image)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        for spot in content.spots:
            if not animated(spot.part):
                self.paint_part(painter, spot, top + row / 2)
        painter.end()
        kept = {
            (c, self.drawn.look, self.contrast, scale)
            for c in (self.drawn.content, self.drawn.previous)
            if c is not None
        }
        self.stills = frozendict(
            {**{k: v for k, v in self.stills.items() if k in kept}, key: image}
        )
        return image

    def paint_part(
        self, painter: QtGui.QPainter, spot: Spot, middle: float
    ) -> None:
        lettering, sizes = self.drawn.look.lettering, self.window_.sizes
        capsule, markers = sizes.capsule, sizes.markers
        match spot.part:
            case Text(text=text, tone=tone, reserve=reserve):
                painter.setFont(inter(sizes.type.reading))
                painter.setPen(
                    color(
                        reading(
                            lettering,
                            tone,
                            self.window_.spec.palette,
                            contrast=self.contrast,
                        )
                    )
                )
                edge, left = (
                    (Qt.AlignmentFlag.AlignRight, spot.x - 1)
                    if reserve
                    else (Qt.AlignmentFlag.AlignLeft, spot.x)
                )
                row = QtCore.QRectF(
                    left, sizes.bar.top, spot.width + 1, capsule.height
                )
                painter.drawText(
                    row, Qt.AlignmentFlag.AlignVCenter | edge, text
                )
            case Glyph(name=name, tone=tone):
                side = round(capsule.icon)
                paint_icon(
                    painter,
                    name,
                    reading(
                        lettering,
                        tone,
                        self.window_.spec.palette,
                        contrast=self.contrast,
                    ),
                    QtCore.QRect(
                        round(spot.x), round(middle - side / 2), side, side
                    ),
                )
            case Charge(tone=tone) as charge:
                ink = reading(
                    lettering,
                    Tone.INK,
                    self.window_.spec.palette,
                    contrast=self.contrast,
                )
                fill = reading(
                    lettering,
                    tone,
                    self.window_.spec.palette,
                    contrast=self.contrast,
                )
                outline_ink = Shade(
                    ink.color, ink.opacity * self.window_.washes.gauge
                )
                paint_charge(
                    painter,
                    QtCore.QPointF(spot.x, middle),
                    sizes.gauge,
                    (color(outline_ink), color(fill), color(ink)),
                    charge,
                )
            case Control():
                pass
            case Marker.WAVE:
                painter.setBrush(
                    color(
                        reading(
                            lettering,
                            Tone.INK,
                            self.window_.spec.palette,
                            contrast=self.contrast,
                        )
                    )
                )
                paint_wave(
                    painter,
                    QtCore.QPointF(spot.x, middle),
                    self.window_.trace(),
                    capsule,
                    markers,
                )
            case Marker.DOTS:
                beat = Beat(
                    self.window_.pulse,
                    self.window_.spec.timing.lag,
                    self.window_.washes.resting,
                )
                paint_dots(
                    painter,
                    QtCore.QRectF(spot.x, middle, spot.width, 0),
                    beat,
                    markers,
                    lettering.ink,
                )
            case Marker.DOT:
                red = color(
                    self.signal(self.window_.spec.palette.red, lettering.ink)
                )
                halo = QtGui.QColor(red)
                halo.setAlphaF(self.window_.washes.halo)
                centre = QtCore.QPointF(spot.x + spot.width / 2, middle)
                paint_dot(painter, halo, centre, markers.halo)
                paint_dot(painter, red, centre, spot.width / 2)
            case _:
                assert_never(spot.part)


class BarWindow(QtWidgets.QWidget):
    def __init__(
        self,
        report: Callable[[Event], None],
        composition: DesktopComposition | None,
        spec: BarSpec,
        log: Callable[[str], None],
    ) -> None:
        super().__init__()
        self.spec = spec
        sizes = self.sizes = spec.sizes
        """Every size the bar paints, as its owner declared them."""
        self.washes = spec.washes
        self.report = report
        """Everything the person does in the bar, as the bar's events."""
        self.log = log
        self.composition = composition
        self.menu: Menu | None = None
        self.capsules: Mapping[Key, Capsule] = frozendict()
        self.pulse = 0.0
        self.samples: deque[float] = deque(
            [0.0] * sizes.capsule.wave_bars, maxlen=sizes.capsule.wave_bars
        )
        self.wave_from: tuple[float, ...] = tuple(self.samples)
        self.wave_progress = 1.0
        self.presentation: Presented | None = None
        self.scene: GlassScene | None = None
        self.panes: tuple[Pane, ...] = ()
        self.pager = Pager(self, sizes)
        self.tray: tuple[Entry, ...] = ()
        self.tray_images: tuple[QtGui.QPixmap | None, ...] = ()
        self.glass = False
        tool_window(self, "Workspace floating bar", on_top=True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        borderless(int(self.winId()))
        windows.allow_activation(int(self.winId()), allowed=False)
        self.glass_timer = QtCore.QTimer(self)
        self.glass_timer.setSingleShot(True)
        self.glass_timer.timeout.connect(self.publish_glass)
        self.deactivation_timer = QtCore.QTimer(self)
        self.deactivation_timer.setTimerType(QtCore.Qt.TimerType.PreciseTimer)
        self.deactivation_timer.setSingleShot(True)
        self.deactivation_timer.timeout.connect(self.dismiss_inactive)

    def show_tray(self, entries: tuple[Entry, ...]) -> None:
        if entries == self.tray:
            return
        self.tray = entries
        self.tray_images = tuple(
            pixmap(entry.image) if entry.image is not None else None
            for entry in entries
        )
        panel = self.capsules.get(Key.PANEL)
        for cell in panel.cells if panel is not None else ():
            cell.update()

    def tray_locations(self) -> tuple[Located, ...]:
        panel = self.capsules.get(Key.PANEL)
        if panel is None or not panel.isVisible():
            return ()
        outer, scale = (
            windows.outer_rect(int(self.winId())),
            self.devicePixelRatioF(),
        )

        def located(cell: MenuCell, slot: int) -> tuple[Located, ...]:
            if slot >= len(self.tray) or not cell.isVisible():
                return ()
            point = cell.mapTo(self, QtCore.QPoint())
            return (
                Located(
                    self.tray[slot],
                    Box(
                        point.x(), point.y(), cell.width(), cell.height()
                    ).on_screen(outer, scale),
                ),
            )

        def slot(cell: MenuCell) -> tuple[Located, ...]:
            match cell.tile.cell.entry:
                case TrayIcon(slot=index):
                    return located(cell, index)
                case _:
                    return ()

        return tuple(found for cell in panel.cells for found in slot(cell))

    def measure(self, view: CapsuleView) -> Content:
        font = self.sizes.type.reading
        return arrange(
            view.slots, lambda text: advance(text.text, font), self.sizes
        )

    def fit(self, menu: Menu) -> float:
        return fitted(
            menu,
            advance,
            self.sizes,
            self.spec.controls.panels[menu.panel].least,
        )

    def capsule(self, drawn: Drawn, *, contrast: bool) -> Capsule:
        existing = self.capsules.get(drawn.view.key)
        if existing is not None:
            existing.show_view(drawn, contrast=contrast)
            return existing
        created = Capsule(self, drawn, contrast=contrast)
        self.capsules = frozendict({**self.capsules, drawn.view.key: created})
        return created

    def present(self, presented: Presented) -> None:
        if presented == self.presentation:
            return
        area = presented.screen
        sizes = self.sizes
        height = round(sizes.bar.top) + math.ceil(presented.height)
        primary = QtGui.QGuiApplication.primaryScreen()
        if self.screen() is not primary:
            self.setScreen(primary)
        if self.geometry() != QtCore.QRect(
            area.left, area.top, area.width, height
        ):
            self.setGeometry(area.left, area.top, area.width, height)
        self.menu = presented.opened
        keys = frozenset(each.view.key for each in presented.drawn)
        for each in presented.drawn:
            capsule = self.capsule(each, contrast=presented.contrast)
            if each.view.key is Key.PANEL:
                capsule.show_menu(self.menu)
            capsule.frame(each.framed)
            capsule.show()
        for key, capsule in self.capsules.items():
            if key not in keys:
                capsule.hide()
        pager = self.pager
        leftmost = math.floor(
            min(
                (each.framed.box.x for each in presented.drawn),
                default=area.width / 2,
            )
        )
        pager.place(
            round(sizes.bar.edge), leftmost - round(sizes.bar.pager_gap)
        )
        pager.apply_look(presented.shell_look)
        self.glass = presented.glass
        self.panes = tuple(
            found
            for each in presented.drawn
            if (found := pane(each, presented, self.spec))
        )
        scale = presented.scale
        match presented.shell_look:
            case GlassLook() as shell_look if pager.isVisibleTo(self):
                bounds = Box(
                    pager.x(), pager.y(), pager.width(), pager.height()
                ).on_device(scale)
                self.panes = (
                    *self.panes,
                    Pane(
                        "desktops",
                        bounds,
                        sizes.bar.radius * scale,
                        1,
                        _veil(shell_look, presented.frost, self.spec.glass),
                    ),
                )
            case GlassLook() | SolidLook():
                pass
        if not self.glass_timer.isActive():
            self.glass_timer.start(0)
        self.presentation = presented

    def trace(self) -> Iterator[float]:
        progress = self.wave_progress
        return (
            before + (after - before) * progress
            for before, after in zip(self.wave_from, self.samples, strict=True)
        )

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
            elif (
                self.menu is not None and not self.deactivation_timer.isActive()
            ):
                self.deactivation_timer.start(16)

    def dismiss_inactive(self) -> None:
        if self.menu is not None and not self.isActiveWindow():
            self.report(Deactivated())

    def bounds(self, key: Key) -> Rect | None:
        capsule = self.capsules.get(key)
        if capsule is None or not capsule.isVisible() or not self.isVisible():
            return None
        shape, strip = capsule.geometry(), self.sizes.bar.top
        area = Box(
            shape.x(), shape.y() + strip, shape.width(), shape.height() - strip
        )
        return area.on_screen(
            windows.outer_rect(int(self.winId())), self.devicePixelRatioF()
        )

    def publish_glass(self) -> None:
        if not self.isVisible() or not self.glass:
            if self.scene is not None:
                self.scene.hide()
            return
        if self.scene is None and self.composition is not None:
            try:
                self.scene = self.composition.scene(
                    "Workspace · Island glass", self.spec.glass.lighting
                )
            except OSError as error:
                self.log(
                    f"Island glass unavailable; using the solid material: {error}"
                )
        if self.scene is None:
            return
        outer = windows.outer_rect(int(self.winId()))
        margin = round(self.sizes.bar.shadow * self.devicePixelRatioF())
        self.scene.place(
            Rect(
                outer.left - margin,
                outer.top,
                outer.right + margin,
                outer.bottom + margin,
            ),
            self.devicePixelRatioF(),
        )
        self.scene.publish(
            tuple(
                Pane(
                    pane.key,
                    shifted(pane.bounds, margin),
                    pane.radius,
                    pane.opacity,
                    pane.veil,
                )
                for pane in self.panes
            )
        )
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
    return Rect(
        bounds.left + margin, bounds.top, bounds.right + margin, bounds.bottom
    )


@dataclass(frozen=True, slots=True)
class Unit:
    x: float
    y: float

    def __post_init__(self) -> None:
        if not (0 <= self.x <= 1 and 0 <= self.y <= 1):
            raise ValueError("A unit point lies inside its box.")


BOLT: Final = (
    Unit(0.62, 0.0),
    Unit(0.0, 0.58),
    Unit(0.44, 0.58),
    Unit(0.34, 1.0),
    Unit(1.0, 0.4),
    Unit(0.56, 0.4),
)
"""The charging bolt: a zigzag from top right to bottom left."""


def paint_charge(
    painter: QtGui.QPainter,
    start: QtCore.QPointF,
    gauge: Gauge,
    inks: tuple[QtGui.QColor, QtGui.QColor, QtGui.QColor],
    charge: Charge,
) -> None:
    outline_ink, fill_ink, bolt_ink = inks
    percent = charge.percent
    body = QtCore.QRectF(
        start.x(),
        start.y() - gauge.height / 2,
        gauge.width - gauge.nub,
        gauge.height,
    )
    edge = gauge.stroke / 2
    painter.save()
    painter.setPen(QtGui.QPen(outline_ink, gauge.stroke))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(
        body.adjusted(edge, edge, -edge, -edge), gauge.corner, gauge.corner
    )
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(outline_ink)
    nub = QtCore.QRectF(
        body.right(),
        start.y() - gauge.nub_height / 2,
        gauge.nub,
        gauge.nub_height,
    )
    painter.drawRoundedRect(nub, gauge.nub / 2, gauge.nub / 2)
    room = body.adjusted(
        *(sides := (gauge.stroke + gauge.inset,) * 2),
        *(-side for side in sides),
    )
    if percent:
        painter.setBrush(fill_ink)
        inner = gauge.corner - gauge.stroke - gauge.inset
        painter.drawRoundedRect(
            QtCore.QRectF(
                room.left(),
                room.top(),
                room.width() * percent / 100,
                room.height(),
            ),
            inner,
            inner,
        )
    if charge.powered:
        width = gauge.bolt * 0.6
        corner = QtCore.QPointF(
            body.center().x() - width / 2, start.y() - gauge.bolt / 2
        )
        bolt = QtGui.QPainterPath()
        bolt.addPolygon(
            QtGui.QPolygonF(
                [
                    corner
                    + QtCore.QPointF(point.x * width, point.y * gauge.bolt)
                    for point in BOLT
                ]
            )
        )
        bolt.closeSubpath()
        painter.setCompositionMode(
            QtGui.QPainter.CompositionMode.CompositionMode_Clear
        )
        painter.strokePath(
            bolt,
            QtGui.QPen(
                Qt.GlobalColor.black,
                2 * gauge.knockout,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
                Qt.PenJoinStyle.RoundJoin,
            ),
        )
        painter.setCompositionMode(
            QtGui.QPainter.CompositionMode.CompositionMode_SourceOver
        )
        painter.fillPath(bolt, bolt_ink)
    painter.restore()


def paint_dot(
    painter: QtGui.QPainter,
    colour: QtGui.QColor,
    centre: QtCore.QPointF,
    radius: float,
) -> None:
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(colour)
    painter.drawEllipse(centre, radius, radius)
