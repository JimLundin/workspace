"""Native key map windows and the draggable live keyboard overlay."""

import traceback
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final, assert_never

lazy from PySide6 import QtCore, QtGui, QtWidgets
lazy from PySide6.QtCore import Qt

from contracts.members import every_member
from desktop_ui.overlay import KeyHighlights, fit_position, nearest_work_area
from desktop_ui.qt_runtime import prepare
from winapi.shapes import Offset, Point, Rect, Size
lazy from desktop_ui.components import typeface
lazy from desktop_ui.components.appearance import GLASS_ACCENT, Scheme, Shade, Tokens, scheme, tokens
lazy from desktop_ui.components.controls import button, label
lazy from desktop_ui.components.widgets import Window, column, glyph, row, segmented, surface, window_style
lazy from desktop_ui.dialogs import bring_forward, near_pointer
lazy from desktop_ui.keymap import PHYSICAL_NAMES, Cap, Kind, keymap
lazy from desktop_ui.overlay_desktop import NativeOverlayDesktop, OverlayDesktop
lazy from desktop_ui.qt_ui import cancel, later
lazy from miryoku.layout import Layer, Scancode

prepare()


_HUES: Final = {
    Kind.MOD: ("#64d2ff", "#0071a4"),
    Kind.LAYER: ("#7ab0f2", "#2f6fc4"),
    Kind.TOOL: ("#ffb340", "#b25000"),
    Kind.APP: ("#30d158", "#248a3d"),
    Kind.SPECIAL: ("#da8fff", "#8944ab"),
}
"""Each binding's hue, legible as text on the dark and the light scheme."""


def _keycap(kind: Kind, theme: Tokens) -> tuple[str, str]:
    """A key's fill and ink: plain keys are solid, a binding tints its key with its hue, the held thumb takes the accent."""
    match kind:
        case Kind.KEY:
            return theme.solid, theme.ink.argb
        case Kind.HELD:
            return GLASS_ACCENT, "#ffffff"
        case Kind.BLANK:
            return theme.fill.argb, theme.ink3.argb
        case Kind.MOD | Kind.LAYER | Kind.TOOL | Kind.APP | Kind.SPECIAL:
            dark, light = _HUES[kind]
            match theme.scheme:
                case Scheme.DARK:
                    return Shade(dark, 0.16).argb, dark
                case Scheme.LIGHT:
                    return Shade(light, 0.12).argb, light
                case _:
                    assert_never(theme.scheme)
        case _:
            assert_never(kind)


PRESSED: Final = every_member(Scheme, {Scheme.DARK: ("#f5f5f7", "#161618"), Scheme.LIGHT: ("#1d1d1f", "#ffffff")})
"""A pressed key lights up in the scheme's ink, unlike any binding's tint."""


def _pressed(theme: Tokens) -> tuple[str, str]:
    return PRESSED[theme.scheme]


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
        return _pressed(self.theme) if name in self.highlighted else _keycap(self.caps[name].kind, self.theme)

    def press(self, names: frozenset[str]) -> None:
        changed = names ^ self.highlighted
        self.highlighted = names
        for name in changed:
            if name in self.boxes:
                self.update(self.boxes[name].toAlignedRect())

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
            face = QtGui.QFont(typeface.FAMILY)
            face.setPixelSize(max(8, round(10 * self.scale)))
            painter.setFont(face)
            painter.setPen(QtGui.QColor(ink if pressed else self.theme.ink3.argb))
            painter.drawText(bounds.adjusted(5 * self.scale, 3 * self.scale, -3, -3), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, name)
            face.setWeight(QtGui.QFont.Weight.DemiBold)
            # Long labels shrink until they fit their key.
            size = round((15 if len(cap.label) <= 5 else 12) * self.scale)
            face.setPixelSize(max(7, size))
            while size > 7 and QtGui.QFontMetricsF(face).horizontalAdvance(cap.label) > bounds.width() - 6 * self.scale:
                size -= 1
                face.setPixelSize(size)
            painter.setFont(face)
            painter.setPen(QtGui.QColor(ink))
            painter.drawText(bounds, Qt.AlignmentFlag.AlignCenter, cap.label)
            face.setPixelSize(max(8, round(10 * self.scale)))
            face.setWeight(QtGui.QFont.Weight.Normal)
            painter.setFont(face)
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
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
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

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag.start(self.read_cursor())
            self.grabMouse()

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
        # The saved overlay position and native moves use physical pixels.
        self.drag.move(self.read_cursor())

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        self.releaseMouse()
        self.drag.end()


class KeymapOverlay:
    __slots__ = (
        "__weakref__",
        "_canvas",
        "_desktop",
        "_drag",
        "_frame",
        "_handle",
        "_handle_frame",
        "_heading",
        "_highlight_timer",
        "_highlights",
        "_position",
        "_view",
        "_window",
    )

    def __init__(self, root: QtWidgets.QApplication, desktop: OverlayDesktop | None = None) -> None:
        self._desktop: OverlayDesktop = desktop if desktop is not None else NativeOverlayDesktop()
        theme = tokens(scheme())
        self._window = QtWidgets.QWidget()
        self._window.setWindowTitle("Workspace keyboard overlay")
        self._window.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
        self._window.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._window.setStyleSheet(window_style(theme))
        self._window.setWindowOpacity(0.55)
        layout = column(surface(self._window, theme, 20))
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(8)
        self._heading = label("", "muted")
        self._heading.setContentsMargins(4, 0, 0, 0)
        layout.addWidget(self._heading)
        self._canvas = KeymapCanvas(theme)
        layout.addWidget(self._canvas)
        self._frame = self._desktop.prepare(self._window, click_through=True)
        self._handle = OverlayHandle(OverlayDrag(self._start_drag, self._drag_to, self._finish_drag), self._desktop.cursor)
        self._handle.setWindowTitle("Workspace keyboard overlay handle")
        self._handle_frame = self._desktop.prepare(self._handle, click_through=False)
        self._position = self._desktop.load_position()
        self._drag: Offset | None = None
        self._view: tuple[Layer | None, str, tuple[Rect, ...]] | None = None
        self._highlights = KeyHighlights()
        self._highlight_timer: QtCore.QTimer | None = None

    def show(self, layer: Layer | None, title: str, work: Rect, *, visible: bool, pressed: frozenset[Scancode] = frozenset()) -> None:
        if not visible:
            self._finish_drag()
            self.set_pressed(frozenset(), reset=True)
            self._handle.hide()
            self._window.hide()
            self._view = None
            return
        areas = self._desktop.work_areas() or (work,)
        view = (layer, title, areas)
        if view == self._view:
            self.set_pressed(pressed)
            return
        if self._position is not None:
            work = nearest_work_area(self._position, areas)
        density = self._window.devicePixelRatioF()
        scale = max(0.2, min(0.85, (work.width / density - 32) / (14 * _UNIT), (work.height / density - 180) / (4 * (_HEIGHT + _GAP))))
        self._heading.setText(f"Workspace keyboard · {title}")
        self._canvas.draw(layer, scale)
        self._view = view
        self.set_pressed(pressed)
        self._window.adjustSize()
        if self._position is None:
            self._position = Point(work.left + work.width // 2, work.bottom - round((self._window.height() + self._handle.height() + 90) * density))
        self._move(self._position)
        self._desktop.present(self._window)
        self._desktop.present(self._handle)

    def set_pressed(self, pressed: frozenset[Scancode], *, reset: bool = False) -> None:
        if reset:
            self._highlights = KeyHighlights()
        if self._view is not None:
            self._highlights = self._highlights.updated(pressed, self._desktop.clock())
            self._paint_highlights()

    def _paint_highlights(self) -> None:
        cancel(self._highlight_timer)
        self._highlight_timer = None
        now = self._desktop.clock()
        self._canvas.press(frozenset(PHYSICAL_NAMES[key] for key in self._highlights.visible(now)))
        if (delay := self._highlights.delay(now)) is not None:
            self._highlight_timer = later(self._window, delay, self._paint_highlights)

    def _move(self, position: Point) -> None:
        self._position = position
        x, y = position.x, position.y
        scale = self._window.devicePixelRatioF()
        width, height = round(self._window.width() * scale), round(self._window.height() * scale)
        handle_width, handle_height = round(self._handle.width() * scale), round(self._handle.height() * scale)
        left, top = x - width // 2, y + handle_height + 4
        self._desktop.move(self._frame, Rect(left, top, left + width, top + height))
        left = x - handle_width // 2
        self._desktop.move(self._handle_frame, Rect(left, y, left + handle_width, y + handle_height))

    def _start_drag(self, point: Point) -> None:
        if self._position is not None and self._view is not None:
            self._drag = point - self._position

    def _drag_to(self, point: Point) -> None:
        if self._drag is not None:
            self._move(point - self._drag)

    def _finish_drag(self) -> None:
        if self._drag is None:
            return
        self._drag = None
        if self._position is not None:
            areas = self._desktop.work_areas()
            if areas:
                scale = self._window.devicePixelRatioF()
                self._move(
                    fit_position(
                        self._position,
                        Size(round(self._window.width() * scale), round((self._window.height() + self._handle.height() + 4) * scale)),
                        nearest_work_area(self._position, areas),
                    )
                )
            try:
                self._desktop.save_position(self._position)
            except OSError:
                traceback.print_exc()


@dataclass(frozen=True, slots=True, weakref_slot=True)
class KeymapWindow:
    window: Window
    canvas: KeymapCanvas
    buttons: tuple[QtWidgets.QToolButton, ...]
    shortcuts: tuple[QtGui.QShortcut, ...]

    @classmethod
    def open(cls, _root: QtWidgets.QApplication) -> KeymapWindow:
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
                "Hold . for Apps: L dictate · K agent · ' dictation toggle · S windows",
                "muted",
            )
        )
        shown = cls(window, canvas, keys, shortcuts)
        shown.draw(None)
        near_pointer(window, 940, 390)
        bring_forward(window, canvas)
        return shown

    def draw(self, layer: Layer | None) -> None:
        self.canvas.draw(layer)
        for key, (_, shown) in zip(self.buttons, _LAYERS, strict=True):
            key.setChecked(shown is layer)

    def close(self) -> None:
        self.window.hide()
        self.window.deleteLater()
