"""Quiet native canvas chrome: the content window, its floating glass capsules and the scroll edge."""

from collections.abc import Callable, Sequence
from typing import Final, assert_never, override

lazy from PySide6 import QtCore, QtGui, QtWidgets
lazy from PySide6.QtCore import Qt

from desktop_ui.canvas_toolbar import Act, Group, Tile
from desktop_ui.components.appearance import GLASS_ACCENT, CanvasBar, GlassLook, SolidLook, Tokens, canvas_style, look
from desktop_ui.components.canvas_look import CAPSULE, CONTROL, SHADOW, WINDOW_RADIUS, CanvasGlass, paint_glass, paint_scroll_edge
from desktop_ui.components.controls import button
from desktop_ui.components.meaning import Tint
from desktop_ui.components.text import color
from desktop_ui.components.widgets import Window, column, row
from desktop_ui.vector_icons import icon
from desktop_ui.window_layout import CANVAS_TITLE
from winapi.appearance import Material


def content_style(theme: Tokens) -> str:
    """The canvas's controls and details; inside solid cards, buttons are filled, never glass."""
    return canvas_style(theme) + (
        f"QToolButton {{ background: {theme.hover.css}; }} QToolButton:hover {{ background: {theme.press.css}; }}"
        f" QToolButton:pressed {{ background: {theme.press.css}; }}"
    )


class CanvasFrame(Window):
    """The native window owns its frame and drag handle; contents have no tabs.

    A neutral solid content window with the kit's large corners while restored.
    """

    def __init__(self, close: Callable[[], None], navigate: Callable[[], None], theme: Tokens) -> None:
        super().__init__(CANVAS_TITLE, close, width=1280, height=880)
        self.navigate: Callable[[], None] = navigate
        self.theme: Tokens = theme
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet(content_style(theme))
        self.setMinimumSize(800, 560)

    @override
    def escaped(self) -> None:
        self.navigate()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.setBrush(QtGui.QColor(self.theme.window))
        painter.setPen(QtGui.QPen(color(self.theme.separator), 1))
        radius = 0 if self.isMaximized() else WINDOW_RADIUS
        painter.drawRoundedRect(QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)


class GlassCapsule(QtWidgets.QFrame):
    """A floating glass capsule over the canvas, holding concentric 28 px controls.

    Its margins hold the shadow, so the glass itself is inset from the widget.
    """

    def __init__(self, parent: QtWidgets.QWidget, theme: Tokens, tint: Tint) -> None:
        super().__init__(parent)
        # The canvas does not observe the material preference yet; its toolbar
        # explicitly retains Qt-painted glass in the current content scheme.
        surface = look(Material.GLASS, CanvasBar(theme.scheme), tint)
        match surface:
            case GlassLook():
                self.surface: CanvasGlass = CanvasGlass(theme.scheme, surface)
            case SolidLook():
                raise ValueError("The canvas glass recipe produced a solid surface.")
            case _:
                assert_never(surface)
        inset = (CAPSULE - CONTROL) // 2
        self.setContentsMargins(SHADOW.left() + inset, SHADOW.top() + inset, SHADOW.right() + inset, SHADOW.bottom() + inset)
        # The row sits in a column so a capsule can grow upward in place (the toolbar's sections).
        self.stack: QtWidgets.QVBoxLayout = column(self)
        self.stack.setSpacing(6)
        self.line: QtWidgets.QWidget = QtWidgets.QWidget(self)
        self.stack.addWidget(self.line)
        self.content: QtWidgets.QHBoxLayout = row(self.line)
        self.content.setSpacing(2)
        ink = self.surface.look.lettering
        # Qt sizes a styled button's contents box: 24 px inside a 2 px border keeps the 28 px circle.
        self.setStyleSheet(
            f"QToolButton#glass {{ border: 2px solid transparent; border-radius: {CONTROL // 2}px; padding: 0; background: transparent;"
            f" min-height: {CONTROL - 4}px; max-height: {CONTROL - 4}px; min-width: {CONTROL - 4}px; max-width: {CONTROL - 4}px;"
            f" color: {ink.ink.css}; font-size: 12px; font-weight: 500; }}"
            f' QToolButton#glass[caption="true"] {{ padding: 0 10px 0 8px; max-width: 160px; }}'
            f" QToolButton#glass:hover {{ background: {ink.hover.css}; }}"
            f" QToolButton#glass:pressed, QToolButton#glass:checked {{ background: {ink.press.css}; }}"
            f" QToolButton#glass:focus {{ border-color: {GLASS_ACCENT}; }}"
        )

    def glass(self) -> QtCore.QRectF:
        return QtCore.QRectF(self.rect()).marginsRemoved(QtCore.QMarginsF(SHADOW))

    def button(self, symbol: str, tip: str, action: Callable[[], None]) -> QtWidgets.QToolButton:
        control = button("", action, tip=tip, name="glass")
        control.setIcon(icon(symbol, self.surface.look.lettering.ink.color))
        control.setIconSize(QtCore.QSize(16, 16))
        return control

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        paint_glass(painter, self.glass(), self.surface)
        painter.end()


TILE_COLUMNS: Final = 4
TILE: Final = QtCore.QSize(100, 64)
TILE_TEXT: Final = TILE.width() - 22
"""Qt's own padding and the tile's border leave this much width for its words."""


def two_lines(words: str, metrics: QtGui.QFontMetrics, width: int) -> str:
    """A tile's words on at most two lines of `width`; what doesn't fit elides the second."""
    first = ""
    rest = words.split()
    while rest and metrics.horizontalAdvance(" ".join((*first.split(), rest[0]))) <= width:
        first = " ".join((*first.split(), rest.pop(0)))
    if not first:
        return metrics.elidedText(words, Qt.TextElideMode.ElideRight, width)
    if not rest:
        return first
    return first + "\n" + metrics.elidedText(" ".join(rest), Qt.TextElideMode.ElideRight, width)


class CanvasToolbar(GlassCapsule):
    """The canvas's island: one glass capsule whose background doubles as a native drag handle.

    Everything the canvas does starts here. Its row holds pinned tiles; expanded, it
    grows upward in place into titled sections of tiles (`canvas_toolbar`).
    """

    def __init__(self, parent: QtWidgets.QWidget, theme: Tokens) -> None:
        super().__init__(parent, theme, Tint.NONE)
        self.setAccessibleName("Canvas controls")
        self.setToolTip("Drag the toolbar background to move the window")
        # The sections scroll within the room the window leaves above the row.
        self.scroller: QtWidgets.QScrollArea = QtWidgets.QScrollArea(self)
        self.scroller.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self.scroller.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroller.setWidgetResizable(True)
        self.expansion: QtWidgets.QWidget = QtWidgets.QWidget()
        self.sections: QtWidgets.QVBoxLayout = column(self.expansion)
        self.sections.setSpacing(4)
        self.scroller.setWidget(self.expansion)
        for widget in (self.scroller, self.scroller.viewport(), self.expansion):
            widget.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            widget.setAutoFillBackground(False)
        self.scroller.hide()
        self.stack.insertWidget(0, self.scroller)
        ink = self.surface.look.lettering
        self.setStyleSheet(
            self.styleSheet() + f" QToolButton#tile {{ border: 2px solid transparent; border-radius: 12px; padding: 4px; background: transparent;"
            f" color: {ink.ink.css}; font-size: 11px; }}"
            f" QToolButton#tile:hover {{ background: {ink.hover.css}; }}"
            f" QToolButton#tile:pressed {{ background: {ink.press.css}; }}"
            f" QToolButton#tile:focus {{ border-color: {GLASS_ACCENT}; }}"
            f" QLabel#tileHeading {{ color: {ink.quiet.css}; font-size: 11px; font-weight: 600; padding: 4px 8px 0 8px; }}"
        )

    def tile_button(self, tile: Tile, perform: Callable[[Act], None]) -> QtWidgets.QToolButton:
        """A pinned tile in the row: its symbol, its words as its tooltip and name."""
        control = self.button(tile.icon, tile.label, lambda: perform(tile.act))
        control.setAccessibleName(tile.label)
        return control

    def show_sections(self, groups: Sequence[Group], perform: Callable[[Act], None], room: int) -> tuple[QtWidgets.QToolButton, ...]:
        """Replace the expanded sections, at most `room` tall; none collapses the toolbar to its row."""
        while self.sections.count():
            taken = self.sections.takeAt(0)
            if taken is not None and (widget := taken.widget()) is not None:
                widget.hide()
                widget.deleteLater()
        tiles: list[QtWidgets.QToolButton] = []
        for group in groups:
            heading = QtWidgets.QLabel(group.title, self.expansion)
            heading.setObjectName("tileHeading")
            self.sections.addWidget(heading)
            grid = QtWidgets.QWidget(self.expansion)
            cells = QtWidgets.QGridLayout(grid)
            cells.setContentsMargins(0, 0, 0, 0)
            cells.setSpacing(2)
            # Every section keeps the same columns, so a short one lines up with those above it.
            cells.setColumnStretch(TILE_COLUMNS, 1)
            for index, tile in enumerate(group.tiles):
                control = self.tile(grid, tile, perform)
                cells.addWidget(control, index // TILE_COLUMNS, index % TILE_COLUMNS)
                tiles.append(control)
            self.sections.addWidget(grid)
        self.sections.activate()
        wanted = self.expansion.sizeHint()
        self.scroller.setFixedSize(wanted.width() + self.scroller.verticalScrollBar().sizeHint().width(), max(0, min(wanted.height(), room)))
        self.scroller.setVisible(bool(groups))
        return tuple(tiles)

    def tile(self, parent: QtWidgets.QWidget, tile: Tile, perform: Callable[[Act], None]) -> QtWidgets.QToolButton:
        control = QtWidgets.QToolButton(parent)
        control.setObjectName("tile")
        control.setFixedSize(TILE)
        control.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        control.setIcon(icon(tile.icon, self.surface.look.lettering.ink.color))
        control.setIconSize(QtCore.QSize(16, 16))
        control.setText(two_lines(tile.label, QtGui.QFontMetrics(control.font()), TILE_TEXT))
        control.setToolTip(tile.label)
        control.setAccessibleName(tile.label)
        control.setCursor(Qt.CursorShape.PointingHandCursor)
        control.clicked.connect(lambda: perform(tile.act))
        return control

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() is Qt.MouseButton.LeftButton and self.glass().contains(event.position()):
            self.window().windowHandle().startSystemMove()
            event.accept()
        else:
            super().mousePressEvent(event)


class ScrollEdge(QtWidgets.QWidget):
    """The soft scroll edge where content passes beneath the floating toolbar; it never takes the pointer."""

    def __init__(self, parent: QtWidgets.QWidget, theme: Tokens) -> None:
        super().__init__(parent)
        self.theme: Tokens = theme
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        paint_scroll_edge(painter, QtCore.QRectF(self.rect()), self.theme)
        painter.end()


class CanvasSurface(QtWidgets.QWidget):
    """Notify the canvas owner to position floating controls after native resize."""

    resized = QtCore.Signal()

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        self.resized.emit()
