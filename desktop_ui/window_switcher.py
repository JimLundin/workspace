"""A searchable window list, independent of the window manager and its workspaces."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Final, override

lazy from PySide6 import QtCore, QtGui, QtWidgets
lazy from PySide6.QtCore import Qt

import winapi.shapes
from components import SWITCHER_TITLE
from desktop_ui.components.appearance import GLASS_ACCENT, ON_ACCENT, Shade, Tokens, scheme, tokens
from desktop_ui.components.text import inter
from desktop_ui.components.typeface import TYPE
from desktop_ui.components.widgets import column, glyph, row, surface_style, window_style
from desktop_ui.qt_runtime import prepare

prepare()


@dataclass(frozen=True, slots=True, kw_only=True)
class SwitcherSpec:
    """The window switcher: a panel with a search field over rows of windows, and its painted shadow."""

    width: int
    tallest: int
    """The panel's width, and the most height it grows to..."""
    chrome: int
    """...with this much beside its rows..."""
    fewest: int
    most: int
    """...sized for this many rows, at least and at most."""
    radius: float
    inset: float
    """Rows sit this far inside the panel, so their corners are concentric with its own."""
    row: int
    text_side: float
    text_top: float
    selected_detail: float
    """A selected row's program line: its ink at this opacity over the accent."""
    field_side: int
    field_top: int
    field_bottom: int
    field_spacing: int
    symbol: str
    symbol_size: int
    placeholder: str
    field_name: str
    list_name: str
    separator: int
    separator_gap: int
    bottom: int
    """Below the hint, inside the panel."""
    hint: str
    hint_side: int
    hint_top: int
    minimized: str
    """After a minimized window's program."""
    shadow: int
    """Transparent room around the panel for its painted shadow..."""
    shadow_lift: int
    """...the panel raised this much inside that room..."""
    shadow_drop: float
    """...the shadow falling this far below it..."""
    shadow_step: int
    shadow_alpha: float
    """...in rings this far apart, the innermost at this alpha out of 255, fading outwards."""


SWITCHER: Final = SwitcherSpec(
    width=640,
    tallest=560,
    chrome=104,
    fewest=1,
    most=7,
    radius=26,
    inset=12,
    row=52,
    text_side=14,
    text_top=7,
    selected_detail=0.75,
    field_side=10,
    field_top=16,
    field_bottom=14,
    field_spacing=10,
    symbol="search",
    symbol_size=20,
    placeholder="Find a window…",
    field_name="Find an open window",
    list_name="Open windows",
    separator=1,
    separator_gap=8,
    bottom=10,
    hint="↑ ↓ select · Enter switch · Escape close",
    hint_side=10,
    hint_top=8,
    minimized=" · minimized",
    shadow=24,
    shadow_lift=8,
    shadow_drop=10,
    shadow_step=2,
    shadow_alpha=6,
)
"""Workspace's switcher; the desktop app opens it with this."""


def matching(windows: Sequence[winapi.shapes.Window], query: str) -> tuple[winapi.shapes.Window, ...]:
    terms = query.casefold().split()
    return tuple(window for window in windows if all(term in f"{window.title} {window.exe}".casefold() for term in terms))


class _Rows(QtWidgets.QStyledItemDelegate):
    """Paints each window as its title over its program, with the selection in the accent."""

    def __init__(self, theme: Tokens, parent: QtWidgets.QListWidget, spec: SwitcherSpec) -> None:
        super().__init__(parent)
        self.theme: Tokens = theme
        self.spec = spec
        self.rows: QtWidgets.QListWidget = parent

    @override
    def sizeHint(self, option: QtWidgets.QStyleOptionViewItem, index: QtCore.QModelIndex | QtCore.QPersistentModelIndex) -> QtCore.QSize:
        return QtCore.QSize(option.rect.width(), self.spec.row)

    @override
    def paint(
        self, painter: QtGui.QPainter, option: QtWidgets.QStyleOptionViewItem, index: QtCore.QModelIndex | QtCore.QPersistentModelIndex
    ) -> None:
        title, _, detail = self.rows.item(index.row()).text().partition("\n")
        selected = bool(option.state & QtWidgets.QStyle.StateFlag.State_Selected)
        bounds, spec = QtCore.QRectF(option.rect).adjusted(0, 1, 0, -1), self.spec
        painter.save()
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        if selected or option.state & QtWidgets.QStyle.StateFlag.State_MouseOver:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QtGui.QColor(GLASS_ACCENT if selected else self.theme.hover.argb))
            painter.drawRoundedRect(bounds, spec.radius - spec.inset, spec.radius - spec.inset)
        text = bounds.adjusted(spec.text_side, spec.text_top, -spec.text_side, -spec.text_top)
        painter.setFont(inter(TYPE.title))
        painter.setPen(QtGui.QColor(ON_ACCENT if selected else self.theme.ink.argb))
        line = QtGui.QFontMetrics(inter(TYPE.title))
        painter.drawText(
            text, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, line.elidedText(title, Qt.TextElideMode.ElideRight, round(text.width()))
        )
        painter.setFont(inter(TYPE.detail))
        painter.setPen(QtGui.QColor(Shade(ON_ACCENT, spec.selected_detail).argb if selected else self.theme.ink2.argb))
        painter.drawText(text, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom, detail)
        painter.restore()


def _style(theme: Tokens, spec: SwitcherSpec) -> str:
    return (
        window_style(theme)
        + surface_style(theme, round(spec.radius))
        + f"""
QLineEdit#query {{ background: transparent; border: none; padding: 0; {TYPE.query.css} }}
QListWidget {{ background: transparent; border: none; outline: none; }}
QListWidget::item {{ background: transparent; border: none; padding: 0; }}
QFrame#separator {{ background: {theme.separator.css}; border: none; }}
QLabel#hint {{ color: {theme.ink3.css}; {TYPE.detail.css} }}
"""
    )


def _field(panel: QtWidgets.QWidget, theme: Tokens, spec: SwitcherSpec) -> tuple[QtWidgets.QHBoxLayout, QtWidgets.QLineEdit]:
    """Spotlight's field: a large borderless query after its symbol."""
    field = row()
    field.setContentsMargins(spec.field_side, spec.field_top, spec.field_side, spec.field_bottom)
    field.setSpacing(spec.field_spacing)
    symbol = QtWidgets.QLabel(panel)
    symbol.setPixmap(glyph(spec.symbol, theme.ink2, spec.symbol_size))
    search = QtWidgets.QLineEdit(panel)
    search.setObjectName("query")
    search.setPlaceholderText(spec.placeholder)
    search.setAccessibleName(spec.field_name)
    field.addWidget(symbol)
    field.addWidget(search, 1)
    return field, search


class WindowSwitcher(QtWidgets.QDialog):
    """A Spotlight-like panel: a large search field over rows, on the kit's solid window."""

    def __init__(self, windows: Sequence[winapi.shapes.Window], focus: Callable[[int], None], spec: SwitcherSpec) -> None:
        super().__init__()
        self.spec = spec
        self.windows = tuple(windows)
        self.focus_window = focus
        theme = tokens(scheme())
        self.setWindowTitle(SWITCHER_TITLE)
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet(_style(theme, spec))
        outer = column(self)
        shadow, lift = spec.shadow, spec.shadow_lift
        outer.setContentsMargins(shadow, shadow - lift, shadow, shadow + lift)
        panel = QtWidgets.QFrame(self)
        panel.setObjectName("surface")
        outer.addWidget(panel)
        layout = column(panel)
        layout.setContentsMargins(round(spec.inset), 0, round(spec.inset), spec.bottom)
        layout.setSpacing(0)
        field, self.search = _field(panel, theme, spec)
        separator = QtWidgets.QFrame(panel)
        separator.setObjectName("separator")
        separator.setFixedHeight(spec.separator)
        self.items = QtWidgets.QListWidget(panel)
        self.items.setAccessibleName(spec.list_name)
        self.items.setItemDelegate(_Rows(theme, self.items, spec))
        self.items.setMouseTracking(True)
        self.items.setVerticalScrollMode(QtWidgets.QAbstractItemView.ScrollMode.ScrollPerPixel)
        hint = QtWidgets.QLabel(spec.hint, panel)
        hint.setObjectName("hint")
        hint.setContentsMargins(spec.hint_side, spec.hint_top, spec.hint_side, 0)
        layout.addLayout(field)
        layout.addWidget(separator)
        layout.addSpacing(spec.separator_gap)
        layout.addWidget(self.items, 1)
        layout.addWidget(hint)
        self.search.textChanged.connect(self.filter)
        self.search.returnPressed.connect(self.activate)

        def picked(_: QtWidgets.QListWidgetItem) -> None:
            self.activate()

        self.items.itemActivated.connect(picked)
        self.search.installEventFilter(self)
        self.filter("")
        rows = max(spec.fewest, min(spec.most, len(windows)))
        self.resize(spec.width + 2 * shadow, min(spec.tallest, spec.chrome + rows * spec.row) + 2 * shadow)

    def filter(self, query: str) -> None:
        self.filtered = matching(self.windows, query)
        self.items.clear()
        for window in self.filtered:
            self.items.addItem(f"{window.title}\n{window.exe.removesuffix('.exe')}" + (self.spec.minimized if window.minimized else ""))
        if self.filtered:
            self.items.setCurrentRow(1 if not query and len(self.filtered) > 1 else 0)

    def activate(self) -> None:
        row = self.items.currentRow()
        if 0 <= row < len(self.filtered):
            handle = self.filtered[row].handle
            self.close()
            self.focus_window(handle)

    @override
    def eventFilter(self, watched: QtCore.QObject, event: QtCore.QEvent) -> bool:
        if event.type() == QtCore.QEvent.Type.KeyPress and isinstance(event, QtGui.QKeyEvent):
            key = event.key()
            if key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
                count = self.items.count()
                if count:
                    self.items.setCurrentRow((self.items.currentRow() + (1 if key == Qt.Key.Key_Down else -1)) % count)
                return True
        return super().eventFilter(watched, event)

    @override
    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        # A frameless translucent window has no system shadow; paint a soft one under the panel.
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        spec = self.spec
        shadow, lift, drop = spec.shadow, spec.shadow_lift, spec.shadow_drop
        panel = QtCore.QRectF(self.rect()).adjusted(shadow, shadow - lift, -shadow, -shadow - lift)
        for step in range(shadow, 0, -spec.shadow_step):
            # Fading from the innermost ring's alpha to 1 at the outermost.
            painter.setBrush(QtGui.QColor(0, 0, 0, round((spec.shadow_alpha - 1) * (1 - step / shadow) ** 2) + 1))
            spread = panel.adjusted(-step, -step + drop, step, step + drop)
            painter.drawRoundedRect(spread, spec.radius + step, spec.radius + step)
