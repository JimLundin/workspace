"""A searchable window list, independent of the window manager and its workspaces."""

from collections.abc import Callable, Sequence
from typing import Final

lazy from PySide6 import QtCore, QtGui, QtWidgets
lazy from PySide6.QtCore import Qt

import winapi.shapes
from assistant.qt_runtime import prepare
from assistant.ui_components import typeface
from assistant.ui_components.appearance import GLASS_ACCENT, Shade, Tokens, scheme, tokens
from assistant.ui_components.widgets import column, glyph, row, surface_style, window_style

prepare()

_RADIUS: Final = 26
"""A window's large corners; rows sit 12 px inside, so theirs are concentric at 14 px."""
_INSET: Final = 12
_SHADOW: Final = 24
"""Transparent room around the panel for its painted shadow."""
_ROW: Final = 52


def matching(windows: Sequence[winapi.shapes.Window], query: str) -> tuple[winapi.shapes.Window, ...]:
    terms = query.casefold().split()
    return tuple(window for window in windows if all(term in f"{window.title} {window.exe}".casefold() for term in terms))


class _Rows(QtWidgets.QStyledItemDelegate):
    """Paints each window as its title over its program, with the selection in the accent."""

    def __init__(self, theme: Tokens, parent: QtCore.QObject) -> None:
        super().__init__(parent)
        self.theme: Tokens = theme

    def sizeHint(self, option: QtWidgets.QStyleOptionViewItem, index: QtCore.QModelIndex | QtCore.QPersistentModelIndex) -> QtCore.QSize:
        return QtCore.QSize(option.rect.width(), _ROW)

    def paint(
        self, painter: QtGui.QPainter, option: QtWidgets.QStyleOptionViewItem, index: QtCore.QModelIndex | QtCore.QPersistentModelIndex
    ) -> None:
        title, _, detail = str(index.data(Qt.ItemDataRole.DisplayRole)).partition("\n")
        selected = bool(option.state & QtWidgets.QStyle.StateFlag.State_Selected)
        bounds = QtCore.QRectF(option.rect).adjusted(0, 1, 0, -1)
        painter.save()
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        if selected or option.state & QtWidgets.QStyle.StateFlag.State_MouseOver:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QtGui.QColor(GLASS_ACCENT if selected else self.theme.hover.argb))
            painter.drawRoundedRect(bounds, _RADIUS - _INSET, _RADIUS - _INSET)
        text = bounds.adjusted(14, 7, -14, -7)
        face = QtGui.QFont(typeface.FAMILY)
        face.setPixelSize(13)
        face.setWeight(QtGui.QFont.Weight.Medium)
        painter.setFont(face)
        painter.setPen(QtGui.QColor("#ffffff" if selected else self.theme.ink.argb))
        line = QtGui.QFontMetrics(face)
        painter.drawText(
            text, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, line.elidedText(title, Qt.TextElideMode.ElideRight, round(text.width()))
        )
        face.setPixelSize(11)
        face.setWeight(QtGui.QFont.Weight.Normal)
        painter.setFont(face)
        painter.setPen(QtGui.QColor(Shade("#ffffff", 0.75).argb if selected else self.theme.ink2.argb))
        painter.drawText(text, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom, detail)
        painter.restore()


def _style(theme: Tokens) -> str:
    return (
        window_style(theme)
        + surface_style(theme, _RADIUS)
        + f"""
QLineEdit#query {{ background: transparent; border: none; padding: 0; font-size: 19px; }}
QListWidget {{ background: transparent; border: none; outline: none; }}
QListWidget::item {{ background: transparent; border: none; padding: 0; }}
QFrame#separator {{ background: {theme.separator.css}; border: none; }}
QLabel#hint {{ color: {theme.ink3.css}; font-size: 11px; }}
"""
    )


def _field(panel: QtWidgets.QWidget, theme: Tokens) -> tuple[QtWidgets.QHBoxLayout, QtWidgets.QLineEdit]:
    """Spotlight's field: a large borderless query after its symbol."""
    field = row()
    field.setContentsMargins(10, 16, 10, 14)
    field.setSpacing(10)
    symbol = QtWidgets.QLabel(panel)
    symbol.setPixmap(glyph("search", theme.ink2, 20))
    search = QtWidgets.QLineEdit(panel)
    search.setObjectName("query")
    search.setPlaceholderText("Find a window…")
    search.setAccessibleName("Find an open window")
    field.addWidget(symbol)
    field.addWidget(search, 1)
    return field, search


class WindowSwitcher(QtWidgets.QDialog):
    """A Spotlight-like panel: a large search field over rows, on the kit's solid window."""

    def __init__(self, windows: Sequence[winapi.shapes.Window], focus: Callable[[int], None]) -> None:
        super().__init__()
        self.windows = tuple(windows)
        self.focus_window = focus
        theme = tokens(scheme())
        self.setWindowTitle("Workspace window switcher")
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet(_style(theme))
        outer = column(self)
        outer.setContentsMargins(_SHADOW, _SHADOW - 8, _SHADOW, _SHADOW + 8)
        panel = QtWidgets.QFrame(self)
        panel.setObjectName("surface")
        outer.addWidget(panel)
        layout = column(panel)
        layout.setContentsMargins(_INSET, 0, _INSET, 10)
        layout.setSpacing(0)
        field, self.search = _field(panel, theme)
        separator = QtWidgets.QFrame(panel)
        separator.setObjectName("separator")
        separator.setFixedHeight(1)
        self.items = QtWidgets.QListWidget(panel)
        self.items.setAccessibleName("Open windows")
        self.items.setItemDelegate(_Rows(theme, self.items))
        self.items.setMouseTracking(True)
        self.items.setVerticalScrollMode(QtWidgets.QAbstractItemView.ScrollMode.ScrollPerPixel)
        hint = QtWidgets.QLabel("↑ ↓ select · Enter switch · Escape close", panel)
        hint.setObjectName("hint")
        hint.setContentsMargins(10, 8, 10, 0)
        layout.addLayout(field)
        layout.addWidget(separator)
        layout.addSpacing(8)
        layout.addWidget(self.items, 1)
        layout.addWidget(hint)
        self.search.textChanged.connect(self.filter)
        self.search.returnPressed.connect(self.activate)

        def picked(_: QtWidgets.QListWidgetItem) -> None:
            self.activate()

        self.items.itemActivated.connect(picked)
        self.search.installEventFilter(self)
        self.filter("")
        self.resize(640 + 2 * _SHADOW, min(560, 104 + max(1, min(7, len(windows))) * _ROW) + 2 * _SHADOW)

    def filter(self, query: str) -> None:
        self.filtered = matching(self.windows, query)
        self.items.clear()
        for window in self.filtered:
            self.items.addItem(f"{window.title}\n{window.exe.removesuffix('.exe')}" + (" · minimized" if window.minimized else ""))
        if self.filtered:
            self.items.setCurrentRow(1 if not query and len(self.filtered) > 1 else 0)

    def activate(self) -> None:
        row = self.items.currentRow()
        if 0 <= row < len(self.filtered):
            handle = self.filtered[row].handle
            self.close()
            self.focus_window(handle)

    def eventFilter(self, watched: QtCore.QObject, event: QtCore.QEvent) -> bool:
        if event.type() == QtCore.QEvent.Type.KeyPress and isinstance(event, QtGui.QKeyEvent):
            key = event.key()
            if key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
                count = self.items.count()
                if count:
                    self.items.setCurrentRow((self.items.currentRow() + (1 if key == Qt.Key.Key_Down else -1)) % count)
                return True
        return super().eventFilter(watched, event)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        # A frameless translucent window has no system shadow; paint a soft one under the panel.
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        panel = QtCore.QRectF(self.rect()).adjusted(_SHADOW, _SHADOW - 8, -_SHADOW, -_SHADOW - 8)
        for step in range(_SHADOW, 0, -2):
            painter.setBrush(QtGui.QColor(0, 0, 0, round(5 * (1 - step / _SHADOW) ** 2) + 1))
            spread = panel.adjusted(-step, -step + 10, step, step + 10)
            painter.drawRoundedRect(spread, _RADIUS + step, _RADIUS + step)
