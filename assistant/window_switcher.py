"""A searchable window list, independent of the window manager and its workspaces."""

from collections.abc import Callable, Sequence

lazy from PySide6 import QtCore, QtGui, QtWidgets
lazy from PySide6.QtCore import Qt

import winapi.shapes
from assistant.notifications import Tone
from assistant.qt_runtime import prepare
from assistant.toast_style import Ink, palette

prepare()


def matching(windows: Sequence[winapi.shapes.Window], query: str) -> tuple[winapi.shapes.Window, ...]:
    terms = query.casefold().split()
    return tuple(window for window in windows if all(term in f"{window.title} {window.exe}".casefold() for term in terms))


class WindowSwitcher(QtWidgets.QDialog):
    def __init__(self, windows: Sequence[winapi.shapes.Window], focus: Callable[[int], None]) -> None:
        super().__init__()
        self.windows = tuple(windows)
        self.focus_window = focus
        self.setWindowTitle("Workspace window switcher")
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        colors, ink = palette(Tone.REPLY), Ink()
        self.setStyleSheet(f"""
QDialog {{ background: {colors.surface}; color: {ink.foreground}; border: 1px solid {colors.edge}; border-radius: 16px; }}
QLineEdit {{ background: transparent; color: {ink.foreground}; border: none; padding: 10px; font: 16px 'Segoe UI'; }}
QListWidget {{ background: transparent; color: {ink.foreground}; border: none; outline: none; font: 13px 'Segoe UI'; }}
QListWidget::item {{ padding: 10px; border-radius: 8px; }}
QListWidget::item:selected {{ background: rgba(150,145,180,65); }}
QLabel {{ color: {ink.secondary}; font: 11px 'Segoe UI'; }}
""")
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        self.search = QtWidgets.QLineEdit(self)
        self.search.setPlaceholderText("Find a window…")
        self.search.setAccessibleName("Find an open window")
        self.items = QtWidgets.QListWidget(self)
        self.items.setAccessibleName("Open windows")
        layout.addWidget(self.search)
        layout.addWidget(self.items, 1)
        layout.addWidget(QtWidgets.QLabel("↑ ↓ select · Enter switch · Escape close", self))
        self.search.textChanged.connect(self.filter)
        self.search.returnPressed.connect(self.activate)
        def picked(_: QtWidgets.QListWidgetItem) -> None:
            self.activate()
        self.items.itemActivated.connect(picked)
        self.search.installEventFilter(self)
        self.filter("")
        self.resize(580, min(480, 130 + max(1, min(7, len(windows))) * 50))

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
