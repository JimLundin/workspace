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
lazy from desktop_ui.components.appearance import GLASS_ACCENT, Scheme, Shade, Tokens, scheme, tokens
lazy from desktop_ui.components.controls import button, label
lazy from desktop_ui.components.text import inter
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
lazy from keyboard.actions import Layer
lazy from keyboard.physical import Scancode

prepare()


@dataclass(frozen=True, slots=True)
class Bindings:
    """How a scheme tints a bound key: its fill's opacity, and each binding's hue, legible as text on the scheme."""

    tint: float
    hues: frozendict[Role, str]


_BINDINGS: Final = every_member(
    Scheme,
    {
        Scheme.DARK: Bindings(
            0.16, frozendict({Role.MOD: "#64d2ff", Role.LAYER: "#7ab0f2", Role.TOOL: "#ffb340", Role.APP: "#30d158", Role.SPECIAL: "#da8fff"})
        ),
        Scheme.LIGHT: Bindings(
            0.12, frozendict({Role.MOD: "#0071a4", Role.LAYER: "#2f6fc4", Role.TOOL: "#b25000", Role.APP: "#248a3d", Role.SPECIAL: "#8944ab"})
        ),
    },
)


def _keycap(role: Role, theme: Tokens) -> tuple[str, str]:
    """A key's fill and ink: plain keys are solid, a binding tints its key with its hue, the held thumb takes the accent."""
    match role:
        case Role.KEY:
            return theme.solid, theme.ink.argb
        case Role.HELD:
            return GLASS_ACCENT, "#ffffff"
        case Role.BLANK:
            return theme.fill.argb, theme.ink3.argb
        case Role.MOD | Role.LAYER | Role.TOOL | Role.APP | Role.SPECIAL:
            bindings = _BINDINGS[theme.scheme]
            hue = bindings.hues[role]
            return Shade(hue, bindings.tint).argb, hue
        case _:
            assert_never(role)


PRESSED: Final = every_member(Scheme, {Scheme.DARK: ("#f5f5f7", "#161618"), Scheme.LIGHT: ("#1d1d1f", "#ffffff")})
"""A pressed key lights up in the scheme's ink, unlike any binding's tint."""


_LAYERS: Final[tuple[tuple[str, Layer | None], ...]] = (("Base", None), *((layer.name.title(), layer) for layer in Layer))
_ROW_START: Final = (0.0, 1.5, 0.0, 1.25, 3.5)
"""Where each row starts, in key widths, as on an ISO keyboard."""
_UNIT, _GAP, _HEIGHT = 64, 5, 56


class KeymapCanvas(QtWidgets.QWidget):
    def __init__(self, theme: Tokens) -> None:
        super().__init__()
        self.theme: Tokens = theme
        self.caps: dict[str, Cap] = {}
        self.boxes: dict[str, QtCore.QRectF] = {}
        self.highlighted: frozenset[str] = frozenset()
        self.scale = 1.0
        self.setAccessibleName("Physical keyboard and current layer")

    def draw(self, layer: Layer | None, scale: float = 1.0) -> None:
        self.scale = scale
        self.caps.clear()
        self.boxes.clear()
        for row_number, (caps, start) in enumerate(zip(keymap(layer), _ROW_START, strict=True)):
            x, y = start * _UNIT * scale, row_number * (_HEIGHT + _GAP) * scale
            for cap in caps:
                size = 6.25 if cap.physical == "Space" else 1.75 if cap.physical == "Caps" else 1.0
                self.caps[cap.physical] = cap
                self.boxes[cap.physical] = QtCore.QRectF(x, y, (size * _UNIT - _GAP) * scale, _HEIGHT * scale)
                x += size * _UNIT * scale
        self.setFixedSize(round(14 * _UNIT * scale), round(len(_ROW_START) * (_HEIGHT + _GAP) * scale))
        self.update()

    def colors(self, name: str) -> tuple[str, str]:
        return PRESSED[self.theme.scheme] if name in self.highlighted else _keycap(self.caps[name].role, self.theme)

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
            fill, ink = self.colors(name)
            pressed = name in self.highlighted
            painter.setPen(QtGui.QPen(QtGui.QColor(fill if pressed else self.theme.solid_edge.argb), 1))
            painter.setBrush(QtGui.QColor(fill))
            corner = max(4.0, 9 * self.scale)
            painter.drawRoundedRect(bounds.adjusted(0.5, 0.5, -0.5, -0.5), corner, corner)
            small = inter(max(8, round(10 * self.scale)), QtGui.QFont.Weight.Normal)
            painter.setFont(small)
            painter.setPen(QtGui.QColor(ink if pressed else self.theme.ink3.argb))
            painter.drawText(bounds.adjusted(5 * self.scale, 3 * self.scale, -3, -3), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, name)
            # Long labels shrink until they fit their key.
            size = round((15 if len(cap.label) <= 5 else 12) * self.scale)
            while (
                size > 7
                and QtGui.QFontMetricsF(inter(size, QtGui.QFont.Weight.DemiBold)).horizontalAdvance(cap.label) > bounds.width() - 6 * self.scale
            ):
                size -= 1
            painter.setFont(inter(max(7, size), QtGui.QFont.Weight.DemiBold))
            painter.setPen(QtGui.QColor(ink))
            painter.drawText(bounds, Qt.AlignmentFlag.AlignCenter, cap.label)
            painter.setFont(small)
            painter.drawText(bounds.adjusted(0, 0, 0, -3 * self.scale), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom, cap.hold)


@dataclass(frozen=True, slots=True)
class OverlayDrag:
    start: Callable[[Point], None]
    move: Callable[[Point], None]
    end: Callable[[], None]


class OverlayHandle(QtWidgets.QWidget):
    """A small capsule above the overlay; the overlay itself lets clicks through."""

    def __init__(self, drag: OverlayDrag, cursor: Callable[[], Point]) -> None:
        super().__init__()
        self.drag: OverlayDrag = drag
        self.read_cursor: Callable[[], Point] = cursor
        tool_window(self, "Workspace keyboard overlay handle", on_top=False)
        self.setAccessibleName("Drag to move the keyboard overlay")
        theme = tokens(scheme())
        self.setStyleSheet(window_style(theme))
        layout = row(surface(self, theme, 14))
        layout.setContentsMargins(12, 6, 14, 6)
        layout.setSpacing(6)
        grip = QtWidgets.QLabel()
        grip.setPixmap(glyph("menu", theme.ink2))
        layout.addWidget(grip)
        layout.addWidget(label("Drag to move", "muted"))
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
    view: tuple[Layer | None, str, tuple[Rect, ...]] | None = None
    highlights: KeyHighlights = field(default_factory=KeyHighlights)
    highlight_timer: QtCore.QTimer | None = None


@dataclass(frozen=True, slots=True, weakref_slot=True)
class KeymapOverlay:
    _desktop: NativeOverlayDesktop
    _window: QtWidgets.QWidget
    _heading: QtWidgets.QLabel
    _canvas: KeymapCanvas
    _frame: int
    _handle: OverlayHandle
    _handle_frame: int
    _state: Cell[_Overlaid]

    @classmethod
    def open(cls) -> KeymapOverlay:
        shown = NativeOverlayDesktop()
        theme = tokens(scheme())
        window = QtWidgets.QWidget()
        tool_window(window, "Workspace keyboard overlay", on_top=False)
        window.setStyleSheet(window_style(theme))
        window.setWindowOpacity(0.55)
        layout = column(surface(window, theme, 20))
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(8)
        heading = label("", "muted")
        heading.setContentsMargins(4, 0, 0, 0)
        layout.addWidget(heading)
        canvas = KeymapCanvas(theme)
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
        handle = OverlayHandle(drag, shown.cursor)
        handle_frame = shown.prepare(handle, click_through=False)
        overlay = cls(shown, window, heading, canvas, frame, handle, handle_frame, Cell(_Overlaid(shown.load_position())))
        return overlay

    def show(self, layer: Layer | None, title: str, work: Rect, *, visible: bool, pressed: frozenset[Scancode] = frozenset()) -> None:
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
        density = self._window.devicePixelRatioF()
        scale = max(0.2, min(0.85, (work.width / density - 32) / (14 * _UNIT), (work.height / density - 180) / (4 * (_HEIGHT + _GAP))))
        self._heading.setText(f"Workspace keyboard · {title}")
        self._canvas.draw(layer, scale)
        self._state.set(replace(self._state.get(), view=view))
        self.set_pressed(pressed)
        self._window.adjustSize()
        placed = self._state.get().position
        if placed is None:
            placed = Point(work.left + work.width // 2, work.bottom - round((self._window.height() + self._handle.height() + 90) * density))
        self._move(placed)
        self._desktop.present(self._window)
        self._desktop.present(self._handle)

    def set_pressed(self, pressed: frozenset[Scancode], *, reset: bool = False) -> None:
        if reset:
            new_highlights = KeyHighlights()
            self._state.set(replace(self._state.get(), highlights=new_highlights))
        if self._state.get().view is not None:
            new_highlights = self._state.get().highlights.updated(pressed, self._desktop.clock())
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
        left, top = x - window.width // 2, y + handle.height + 4
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
                    Size(round(self._window.width() * scale), round((self._window.height() + self._handle.height() + 4) * scale)),
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
    def open(cls) -> KeymapWindow:
        # The buttons and shortcuts act on the window record made just after them.
        def close() -> None:
            window.hide()
            window.deleteLater()

        def chooser(layer: Layer | None) -> Callable[[], None]:
            return lambda: shown.draw(layer)

        window = Window("Workspace key map", close, width=940, height=390)
        layout = column(window)
        layout.setContentsMargins(20, 16, 20, 16)
        keys = tuple(button(name, chooser(layer)) for name, layer in _LAYERS)
        for key in keys:
            key.setCheckable(True)
        shortcuts = tuple(QtGui.QShortcut(QtGui.QKeySequence(str(index + 1)), window) for index in range(len(_LAYERS)))
        for shortcut, (_, layer) in zip(shortcuts, _LAYERS, strict=True):
            shortcut.activated.connect(chooser(layer))
        buttons = row()
        buttons.addWidget(segmented(list(keys)))
        buttons.addStretch()
        layout.addLayout(buttons)
        canvas = KeymapCanvas(tokens(scheme()))
        layout.addWidget(canvas)
        layout.addWidget(
            label(
                "Hold . for Apps: L dictate · ' dictation toggle · S windows",
                "muted",
            )
        )
        shown = cls(window, canvas, keys, shortcuts)
        shown.draw(None)
        near_pointer(window, 940, 390)
        show_window(window, focus=True, target=canvas)
        return shown

    def draw(self, layer: Layer | None) -> None:
        self.canvas.draw(layer)
        for key, (_, shown) in zip(self.buttons, _LAYERS, strict=True):
            key.setChecked(shown is layer)

    def close(self) -> None:
        self.window.hide()
        self.window.deleteLater()
