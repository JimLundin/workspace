"""Native key map windows and the draggable live keyboard overlay."""

import traceback
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Final, assert_never, override

lazy from PySide6 import QtCore, QtGui, QtWidgets
lazy from PySide6.QtCore import Qt

from cell import Cell
from contracts.members import every_member
from desktop_ui.overlay import KeyHighlights, fit_position, nearest_work_area
from desktop_ui.qt_runtime import prepare
from winapi.shapes import Offset, Point, Rect, Size
lazy from desktop_ui.components.appearance import GLASS_ACCENT, ON_ACCENT, Scheme, Shade, Tokens, scheme, tokens
lazy from desktop_ui.components.controls import button, label
lazy from desktop_ui.components.text import inter
lazy from desktop_ui.components.typeface import TYPE, Font
lazy from desktop_ui.components.widgets import (
    Window,
    column,
    device_size,
    glyph,
    near_pointer,
    row,
    segmented,
    show_window,
    surface,
    tool_window,
    window_style,
)
lazy from desktop_ui.keymap import PHYSICAL_NAMES, Cap, Role, keymap
lazy from desktop_ui.overlay_desktop import NativeOverlayDesktop
lazy from desktop_ui.qt_ui import cancel, later
lazy from keyboard import settings
lazy from keyboard.actions import Layer
lazy from keyboard.physical import Scancode

prepare()


@dataclass(frozen=True, slots=True)
class Bindings:
    """How a scheme tints a bound key: its fill's opacity, and each binding's hue, legible as text on the scheme."""

    tint: float
    hues: frozendict[Role, str]


@dataclass(frozen=True, slots=True)
class Lit:
    """A key's fill and ink."""

    fill: str
    ink: str


@dataclass(frozen=True, slots=True, kw_only=True)
class KeysSpec:
    """The drawn keyboard: its grid, its keys' faces, and how a binding or a press colours them."""

    unit: float
    """One key width, gap included, before the drawing's scale."""
    gap: float
    height: float
    rows: tuple[float, ...]
    """Where each row starts, in key widths, as on an ISO keyboard."""
    columns: float
    """The keyboard's width, in key widths."""
    widths: frozendict[str, float]
    """Keys wider than one, by physical name."""
    corner: float
    corner_least: float
    name: Font
    """A key's physical name and its hold, at the drawing's scale but never below `name_least`."""
    name_least: int
    name_inset: float
    hold_bottom: float
    legend: Font
    legend_long: Font
    """The legend of a key whose legend is longer than `legend_short` characters..."""
    legend_short: int
    legend_least: int
    """...shrinking to fit its key, never below this size."""
    legend_fit: float
    """Room kept beside a legend inside its key."""
    held: Lit
    """The held thumb takes the accent."""
    bindings: frozendict[Scheme, Bindings]
    pressed: frozendict[Scheme, Lit]
    """A pressed key lights up in the scheme's ink, unlike any binding's tint."""


@dataclass(frozen=True, slots=True, kw_only=True)
class OverlaySpec:
    """The live keyboard overlay and the handle that moves it."""

    opacity: float
    radius: float
    side: float
    top: float
    bottom: float
    spacing: float
    heading_inset: float
    heading: str
    """Followed by the layer's title."""
    smallest: float
    largest: float
    """The drawing's scale, within these bounds..."""
    margin: float
    """...fitting the work area's width less this..."""
    reserve: float
    """...and its height less this."""
    rest: float
    """How far above the work area's bottom the overlay first appears."""
    handle_radius: float
    handle_leading: float
    handle_trailing: float
    handle_padding: float
    handle_spacing: float
    handle_glyph: str
    handle_text: str
    handle_gap: int
    """Between the handle and the overlay below it."""
    tap: float
    """Seconds a tapped key stays lit, so a quick tap is still seen."""


@dataclass(frozen=True, slots=True, kw_only=True)
class MapWindowSpec:
    width: int
    height: int
    side: float
    top: float
    hint: str


@dataclass(frozen=True, slots=True, kw_only=True)
class KeymapSpec:
    keys: KeysSpec
    overlay: OverlaySpec
    window: MapWindowSpec


KEYMAP: Final = KeymapSpec(
    keys=KeysSpec(
        unit=64,
        gap=5,
        height=56,
        rows=(0.0, 1.5, 0.0, 1.25, 3.5),
        columns=14,
        widths=frozendict({"Space": 6.25, "Caps": 1.75}),
        corner=9,
        corner_least=4,
        name=TYPE.keycap_name,
        name_least=8,
        name_inset=3,
        hold_bottom=3,
        legend=TYPE.keycap,
        legend_long=TYPE.keycap_long,
        legend_short=5,
        legend_least=7,
        legend_fit=6,
        held=Lit(GLASS_ACCENT, ON_ACCENT),
        bindings=every_member(
            Scheme,
            {
                Scheme.DARK: Bindings(
                    0.16, frozendict({Role.MOD: "#64d2ff", Role.LAYER: "#7ab0f2", Role.TOOL: "#ffb340", Role.APP: "#30d158", Role.SPECIAL: "#da8fff"})
                ),
                Scheme.LIGHT: Bindings(
                    0.12, frozendict({Role.MOD: "#0071a4", Role.LAYER: "#2f6fc4", Role.TOOL: "#b25000", Role.APP: "#248a3d", Role.SPECIAL: "#8944ab"})
                ),
            },
        ),
        pressed=every_member(Scheme, {Scheme.DARK: Lit("#f5f5f7", "#161618"), Scheme.LIGHT: Lit("#1d1d1f", "#ffffff")}),
    ),
    overlay=OverlaySpec(
        opacity=0.55,
        radius=20,
        side=12,
        top=10,
        bottom=12,
        spacing=8,
        heading_inset=4,
        heading="Workspace keyboard",
        smallest=0.2,
        largest=0.85,
        margin=32,
        reserve=180,
        rest=90,
        handle_radius=14,
        handle_leading=12,
        handle_trailing=14,
        handle_padding=6,
        handle_spacing=6,
        handle_glyph="menu",
        handle_text="Drag to move",
        handle_gap=4,
        tap=0.12,
    ),
    window=MapWindowSpec(width=940, height=390, side=20, top=16, hint="Hold . for Apps: L dictate · ' dictation toggle · S windows"),
)
"""Workspace's key map and overlay; the desktop app opens them with it."""


def _keycap(role: Role, theme: Tokens, keys: KeysSpec) -> Lit:
    """A key's fill and ink: plain keys are solid, a binding tints its key with its hue, the held thumb takes the accent."""
    match role:
        case Role.KEY:
            return Lit(theme.solid, theme.ink.argb)
        case Role.HELD:
            return keys.held
        case Role.BLANK:
            return Lit(theme.fill.argb, theme.ink3.argb)
        case Role.MOD | Role.LAYER | Role.TOOL | Role.APP | Role.SPECIAL:
            bindings = keys.bindings[theme.scheme]
            hue = bindings.hues[role]
            return Lit(Shade(hue, bindings.tint).argb, hue)
        case _:
            assert_never(role)


_LAYERS: Final[tuple[Layer, ...]] = (settings.Layers.BASE, *(layer for layer in settings.Layers if layer is not settings.Layers.BASE))
"""The key map's tabs: the base layer first, then the held layers."""


def keyboard_height(keys: KeysSpec) -> float:
    """The drawn keyboard's height before its scale: every row with the gap below it."""
    return len(keys.rows) * (keys.height + keys.gap)


class KeymapCanvas(QtWidgets.QWidget):
    def __init__(self, theme: Tokens, keys: KeysSpec) -> None:
        super().__init__()
        self.theme: Tokens = theme
        self.keys = keys
        self.caps: dict[str, Cap] = {}
        self.boxes: dict[str, QtCore.QRectF] = {}
        self.highlighted: frozenset[str] = frozenset()
        self.scale = 1.0
        self.setAccessibleName("Physical keyboard and current layer")

    def draw(self, layer: Layer, scale: float = 1.0) -> None:
        self.scale = scale
        self.caps.clear()
        self.boxes.clear()
        keys = self.keys
        for row_number, (caps, start) in enumerate(zip(keymap(layer), keys.rows, strict=True)):
            x, y = start * keys.unit * scale, row_number * (keys.height + keys.gap) * scale
            for cap in caps:
                size = keys.widths.get(cap.physical, 1.0)
                self.caps[cap.physical] = cap
                self.boxes[cap.physical] = QtCore.QRectF(x, y, (size * keys.unit - keys.gap) * scale, keys.height * scale)
                x += size * keys.unit * scale
        self.setFixedSize(round(keys.columns * keys.unit * scale), round(keyboard_height(keys) * scale))
        self.update()

    def colors(self, name: str) -> Lit:
        return self.keys.pressed[self.theme.scheme] if name in self.highlighted else _keycap(self.caps[name].role, self.theme, self.keys)

    def press(self, names: frozenset[str]) -> None:
        changed = names ^ self.highlighted
        self.highlighted = names
        for name in changed:
            if name in self.boxes:
                self.update(self.boxes[name].toAlignedRect())

    @override
    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        for name, cap in self.caps.items():
            bounds = self.boxes[name]
            lit = self.colors(name)
            fill, ink, keys = lit.fill, lit.ink, self.keys
            pressed = name in self.highlighted
            painter.setPen(QtGui.QPen(QtGui.QColor(fill if pressed else self.theme.solid_edge.argb), 1))
            painter.setBrush(QtGui.QColor(fill))
            corner = max(keys.corner_least, keys.corner * self.scale)
            painter.drawRoundedRect(bounds.adjusted(0.5, 0.5, -0.5, -0.5), corner, corner)
            small = inter(Font(max(keys.name_least, round(keys.name.pixels * self.scale)), keys.name.weight))
            painter.setFont(small)
            painter.setPen(QtGui.QColor(ink if pressed else self.theme.ink3.argb))
            inset = keys.name_inset
            named = bounds.adjusted((inset + 2) * self.scale, inset * self.scale, -inset, -inset)
            painter.drawText(named, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, name)
            # Long labels shrink until they fit their key.
            legend = keys.legend if len(cap.label) <= keys.legend_short else keys.legend_long
            size = round(legend.pixels * self.scale)
            room = bounds.width() - keys.legend_fit * self.scale
            while size > keys.legend_least and QtGui.QFontMetricsF(inter(Font(size, legend.weight))).horizontalAdvance(cap.label) > room:
                size -= 1
            painter.setFont(inter(Font(max(keys.legend_least, size), legend.weight)))
            painter.setPen(QtGui.QColor(ink))
            painter.drawText(bounds, Qt.AlignmentFlag.AlignCenter, cap.label)
            painter.setFont(small)
            painter.drawText(
                bounds.adjusted(0, 0, 0, -keys.hold_bottom * self.scale), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom, cap.hold
            )


@dataclass(frozen=True, slots=True)
class OverlayDrag:
    start: Callable[[Point], None]
    move: Callable[[Point], None]
    end: Callable[[], None]


class OverlayHandle(QtWidgets.QWidget):
    """A small capsule above the overlay; the overlay itself lets clicks through."""

    def __init__(self, drag: OverlayDrag, cursor: Callable[[], Point], spec: OverlaySpec) -> None:
        super().__init__()
        self.drag: OverlayDrag = drag
        self.read_cursor: Callable[[], Point] = cursor
        tool_window(self, "Workspace keyboard overlay handle", on_top=False)
        self.setAccessibleName("Drag to move the keyboard overlay")
        theme = tokens(scheme())
        self.setStyleSheet(window_style(theme))
        layout = row(surface(self, theme, round(spec.handle_radius)))
        padding = round(spec.handle_padding)
        layout.setContentsMargins(round(spec.handle_leading), padding, round(spec.handle_trailing), padding)
        layout.setSpacing(round(spec.handle_spacing))
        grip = QtWidgets.QLabel()
        grip.setPixmap(glyph(spec.handle_glyph, theme.ink2))
        layout.addWidget(grip)
        layout.addWidget(label(spec.handle_text, "muted"))
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self.adjustSize()

    @override
    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag.start(self.read_cursor())
            self.grabMouse()

    @override
    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
        # The saved overlay position and native moves use physical pixels.
        self.drag.move(self.read_cursor())

    @override
    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        self.releaseMouse()
        self.drag.end()


@dataclass(frozen=True, slots=True)
class _Overlaid:
    position: Point | None
    """Where the person put the overlay's handle; None until it is first placed."""
    drag: Offset | None = None
    """The pointer's offset from the handle while dragging."""
    view: tuple[Layer, str, tuple[Rect, ...]] | None = None
    highlights: KeyHighlights = field(default_factory=KeyHighlights)
    highlight_timer: QtCore.QTimer | None = None


@dataclass(frozen=True, slots=True, weakref_slot=True)
class KeymapOverlay:
    _spec: KeymapSpec
    _desktop: NativeOverlayDesktop
    _window: QtWidgets.QWidget
    _heading: QtWidgets.QLabel
    _canvas: KeymapCanvas
    _frame: int
    _handle: OverlayHandle
    _handle_frame: int
    _state: Cell[_Overlaid]

    @classmethod
    def open(cls, spec: KeymapSpec) -> KeymapOverlay:
        shown, look = NativeOverlayDesktop(), spec.overlay
        theme = tokens(scheme())
        window = QtWidgets.QWidget()
        tool_window(window, "Workspace keyboard overlay", on_top=False)
        window.setStyleSheet(window_style(theme))
        window.setWindowOpacity(look.opacity)
        layout = column(surface(window, theme, round(look.radius)))
        layout.setContentsMargins(round(look.side), round(look.top), round(look.side), round(look.bottom))
        layout.setSpacing(round(look.spacing))
        heading = label("", "muted")
        heading.setContentsMargins(round(look.heading_inset), 0, 0, 0)
        layout.addWidget(heading)
        canvas = KeymapCanvas(theme, spec.keys)
        layout.addWidget(canvas)
        frame = shown.prepare(window, click_through=True)

        # The handle reports its drag to the overlay made just after it.
        def start(point: Point) -> None:
            overlay._start_drag(point)

        def move(point: Point) -> None:
            overlay._drag_to(point)

        def end() -> None:
            overlay._finish_drag()

        drag = OverlayDrag(start, move, end)
        handle = OverlayHandle(drag, shown.cursor, look)
        handle_frame = shown.prepare(handle, click_through=False)
        overlay = cls(spec, shown, window, heading, canvas, frame, handle, handle_frame, Cell(_Overlaid(shown.load_position())))
        return overlay

    def show(self, layer: Layer, title: str, work: Rect, *, visible: bool, pressed: frozenset[Scancode] = frozenset()) -> None:
        if not visible:
            self._finish_drag()
            self.set_pressed(frozenset(), reset=True)
            self._handle.hide()
            self._window.hide()
            self._state.set(replace(self._state.get(), view=None))
            return
        areas = self._desktop.work_areas() or (work,)
        view = (layer, title, areas)
        if view == self._state.get().view:
            self.set_pressed(pressed)
            return
        if placed := self._state.get().position:
            work = nearest_work_area(placed, areas)
        density, look, keys = self._window.devicePixelRatioF(), self._spec.overlay, self._spec.keys
        across = (work.width / density - look.margin) / (keys.columns * keys.unit)
        down = (work.height / density - look.reserve) / keyboard_height(keys)
        scale = max(look.smallest, min(look.largest, across, down))
        self._heading.setText(f"{look.heading} · {title}")
        self._canvas.draw(layer, scale)
        self._state.set(replace(self._state.get(), view=view))
        self.set_pressed(pressed)
        self._window.adjustSize()
        placed = self._state.get().position
        if placed is None:
            placed = Point(work.left + work.width // 2, work.bottom - round((self._window.height() + self._handle.height() + look.rest) * density))
        self._move(placed)
        self._desktop.present(self._window)
        self._desktop.present(self._handle)

    def set_pressed(self, pressed: frozenset[Scancode], *, reset: bool = False) -> None:
        if reset:
            new_highlights = KeyHighlights()
            self._state.set(replace(self._state.get(), highlights=new_highlights))
        if self._state.get().view is not None:
            new_highlights = self._state.get().highlights.updated(pressed, self._desktop.clock(), self._spec.overlay.tap)
            self._state.set(replace(self._state.get(), highlights=new_highlights))
            self._paint_highlights()

    def _paint_highlights(self) -> None:
        cancel(self._state.get().highlight_timer)
        self._state.set(replace(self._state.get(), highlight_timer=None))
        now = self._desktop.clock()
        self._canvas.press(frozenset(PHYSICAL_NAMES[key] for key in self._state.get().highlights.visible(now)))
        if (delay := self._state.get().highlights.delay(now)) is not None:
            new_highlight_timer = later(self._window, delay, self._paint_highlights)
            self._state.set(replace(self._state.get(), highlight_timer=new_highlight_timer))

    def _move(self, position: Point) -> None:
        self._state.set(replace(self._state.get(), position=position))
        x, y = position.x, position.y
        scale = self._window.devicePixelRatioF()
        window, handle = device_size(self._window, scale), device_size(self._handle, scale)
        left, top = x - window.width // 2, y + handle.height + self._spec.overlay.handle_gap
        self._desktop.move(self._frame, Rect(left, top, left + window.width, top + window.height))
        left = x - handle.width // 2
        self._desktop.move(self._handle_frame, Rect(left, y, left + handle.width, y + handle.height))

    def _start_drag(self, point: Point) -> None:
        overlaid = self._state.get()
        if overlaid.position is not None and overlaid.view is not None:
            self._state.set(replace(overlaid, drag=point - overlaid.position))

    def _drag_to(self, point: Point) -> None:
        if offset := self._state.get().drag:
            self._move(point - offset)

    def _finish_drag(self) -> None:
        if self._state.get().drag is None:
            return
        self._state.set(replace(self._state.get(), drag=None))
        if placed := self._state.get().position:
            areas = self._desktop.work_areas()
            if areas:
                scale = self._window.devicePixelRatioF()
                placed = fit_position(
                    placed,
                    Size(
                        round(self._window.width() * scale),
                        round((self._window.height() + self._handle.height() + self._spec.overlay.handle_gap) * scale),
                    ),
                    nearest_work_area(placed, areas),
                )
                self._move(placed)
            try:
                self._desktop.save_position(placed)
            except OSError:
                traceback.print_exc()


@dataclass(frozen=True, slots=True, weakref_slot=True)
class KeymapWindow:
    window: Window
    canvas: KeymapCanvas
    buttons: tuple[QtWidgets.QToolButton, ...]
    shortcuts: tuple[QtGui.QShortcut, ...]

    @classmethod
    def open(cls, spec: KeymapSpec) -> KeymapWindow:
        # The buttons and shortcuts act on the window record made just after them.
        def close() -> None:
            window.hide()
            window.deleteLater()

        def chooser(layer: Layer) -> Callable[[], None]:
            return lambda: shown.draw(layer)

        size = spec.window
        window = Window("Workspace key map", close, width=size.width, height=size.height)
        layout = column(window)
        layout.setContentsMargins(round(size.side), round(size.top), round(size.side), round(size.top))
        keys = tuple(button(layer.name.title(), chooser(layer)) for layer in _LAYERS)
        for key in keys:
            key.setCheckable(True)
        shortcuts = tuple(QtGui.QShortcut(QtGui.QKeySequence(str(index + 1)), window) for index in range(len(_LAYERS)))
        for shortcut, layer in zip(shortcuts, _LAYERS, strict=True):
            shortcut.activated.connect(chooser(layer))
        buttons = row()
        buttons.addWidget(segmented(list(keys)))
        buttons.addStretch()
        layout.addLayout(buttons)
        canvas = KeymapCanvas(tokens(scheme()), spec.keys)
        layout.addWidget(canvas)
        layout.addWidget(label(size.hint, "muted"))
        shown = cls(window, canvas, keys, shortcuts)
        shown.draw(settings.Layers.BASE)
        near_pointer(window, size.width, size.height)
        show_window(window, focus=True, target=canvas)
        return shown

    def draw(self, layer: Layer) -> None:
        self.canvas.draw(layer)
        for key, shown in zip(self.buttons, _LAYERS, strict=True):
            key.setChecked(shown is layer)

    def close(self) -> None:
        self.window.hide()
        self.window.deleteLater()
