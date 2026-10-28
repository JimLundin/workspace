"""Shared native panel controls and styling. Qt objects stay on the UI thread."""
# pyright: reportUnknownMemberType=false, reportUnknownArgumentType=false

from collections.abc import Callable

lazy from PySide6 import QtWidgets
lazy from PySide6.QtCore import Qt

from assistant.qt_runtime import prepare

prepare()

STYLE = """
QWidget { color: #d8e0ea; font-family: 'Segoe UI'; font-size: 12px; }
QLabel { background: transparent; border: none; }
QLabel#muted { color: #95a5b7; font-size: 10px; }
QLabel#title { font-size: 12px; font-weight: 600; }
QLabel#status { color: #f0cc8c; font-size: 10px; }
QToolButton, QPushButton { border: 1px solid transparent; border-radius: 6px; background: transparent; padding: 6px 9px; font-size: 11px; }
QToolButton:hover, QPushButton:hover { background: rgba(255,255,255,15); }
QToolButton:pressed, QPushButton:pressed { background: rgba(184,210,255,35); }
QToolButton:focus, QPushButton:focus, QComboBox:focus { border: 1px solid #b8d2ff; }
QToolButton:disabled, QPushButton:disabled { color: #687584; }
QToolButton#primary, QPushButton#primary { background: #d9c8f3; color: #272534; padding: 8px 12px; font-weight: 600; }
QToolButton#primary:hover, QPushButton#primary:hover { background: #ecddff; }
QToolButton#chip { background: rgba(200,212,240,12); border: 1px solid rgba(188,204,228,32); padding: 3px 6px; font-size: 9px; }
QToolButton:checked { background: rgba(255,255,255,14); color: #dce5f3; }
QLineEdit, QPlainTextEdit, QTextBrowser, QTableWidget {
 background: #202832; border: 1px solid #3c4754; border-radius: 7px; padding: 8px;
}
QPlainTextEdit:focus, QLineEdit:focus { border: 1px solid #a5bde4; }
QLineEdit { selection-background-color: #536888; }
QTextBrowser { selection-background-color: #67567d; }
QScrollBar:vertical { background: transparent; width: 6px; margin: 2px; }
QScrollBar::handle:vertical { background: #606c7a; border-radius: 2px; min-height: 24px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { background: transparent; height: 6px; }
QScrollBar::handle:horizontal { background: #606c7a; border-radius: 2px; min-width: 24px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QComboBox { background: #26313d; border: 1px solid #44515f; border-radius: 6px; padding: 5px 12px; }
QComboBox QAbstractItemView { background: #26313d; selection-background-color: #40516b; }
QListWidget, QTreeWidget { background: #232b34; border: none; outline: none; }
QTreeWidget::item { padding: 8px 4px; }
QTreeWidget::item:selected { background: #35465b; }
QListWidget::item { padding: 10px 14px; border-radius: 8px; }
QListWidget::item:selected { background: #35465b; color: #eaf0fa; }
QListWidget::item:hover { background: #29394b; }
QDialog, QMenu { background: #252d37; }
QMenu { border: 1px solid #5b6980; padding: 6px; }
QMenu::item { padding: 8px 22px; border-radius: 5px; }
QMenu::item:selected { background: #435371; }
QHeaderView::section { background: #252c34; color: #8fa2b5; padding: 8px; border: none; font-size: 10px; }
QTableWidget { gridline-color: #39454e; selection-background-color: #344b51; border: none; background: transparent; }
QTableWidget::item { padding: 8px; border-bottom: 1px solid #323d47; }
QCheckBox { spacing: 7px; }
QTabWidget::pane { border: 1px solid #3b4755; border-radius: 8px; }
QTabBar::tab { background: #232b34; color: #a3b0c1; padding: 10px 16px; }
QTabBar::tab:selected { background: #354252; color: #e9e8e4; }
QToolTip { background: #253140; color: #eef2f7; border: 1px solid #71819c; padding: 6px; }
"""


def button(text: str, callback: Callable[[], None], *, tip: str = "", name: str = "") -> QtWidgets.QToolButton:
    widget = QtWidgets.QToolButton()
    widget.setText(text)
    widget.setAccessibleName(tip or text)
    widget.setToolTip(tip)
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    if name:
        widget.setObjectName(name)
    # Plain slotted controllers need not support weak references just because a
    # Qt signal owns a callback. Qt retains this small closure with the button.
    widget.clicked.connect(lambda: callback())  # noqa: PLW0108  # Qt cannot weak-reference every slotted callback owner.
    return widget


def label(text: str, name: str = "") -> QtWidgets.QLabel:
    widget = QtWidgets.QLabel(text)
    widget.setObjectName(name)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    return widget
