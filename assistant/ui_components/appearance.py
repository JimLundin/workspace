"""Workspace's colour tokens, bubble palettes and the Qt stylesheets generated from them.

Quiet blue and lilac glass, with opaque ink and a dark solid fallback.
"""

from dataclasses import dataclass
from typing import Final, assert_never

from assistant.feed_origin import App
from assistant.notifications import Tone

ACCENT: Final = "#d9c8f3"  # primary actions and the voice legend
INK: Final = "#f6f3ff"
SECONDARY: Final = "#e0dced"
USER: Final = "#c7dcff"
SURFACE: Final = "#262337"
EDGE: Final = "#716a87"

# The keyboard overlay keeps its neutral charcoal and blue held-key accent.
OVERLAY_BACKGROUND: Final = "#1f2124"
OVERLAY_INK: Final = "#e8e6e3"
OVERLAY_MUTED: Final = "#9a9893"
OVERLAY_ACCENT: Final = "#6aa9ff"
OVERLAY_SURFACE: Final = "#2b2e33"

CONTROL_STYLE: Final = f"""
QWidget {{ color: #d8e0ea; font-family: 'Segoe UI'; font-size: 12px; }}
QLabel {{ background: transparent; border: none; }}
QLabel#muted {{ color: #95a5b7; font-size: 10px; }}
QLabel#title {{ font-size: 12px; font-weight: 600; }}
QLabel#status {{ color: #f0cc8c; font-size: 10px; }}
QToolButton, QPushButton {{ border: 1px solid transparent; border-radius: 6px; background: transparent; padding: 6px 9px; font-size: 11px; }}
QToolButton:hover, QPushButton:hover {{ background: rgba(255,255,255,15); }}
QToolButton:pressed, QPushButton:pressed {{ background: rgba(184,210,255,35); }}
QToolButton:focus, QPushButton:focus, QComboBox:focus {{ border: 1px solid #b8d2ff; }}
QToolButton:disabled, QPushButton:disabled {{ color: #687584; }}
QToolButton#primary, QPushButton#primary {{ background: {ACCENT}; color: #272534; padding: 8px 12px; font-weight: 600; }}
QToolButton#primary:hover, QPushButton#primary:hover {{ background: #ecddff; }}
QToolButton#chip {{ background: rgba(200,212,240,12); border: 1px solid rgba(188,204,228,32); padding: 3px 6px; font-size: 9px; }}
QToolButton:checked {{ background: rgba(255,255,255,14); color: #dce5f3; }}
QLineEdit, QPlainTextEdit, QTextBrowser, QTableWidget {{
 background: #202832; border: 1px solid #3c4754; border-radius: 7px; padding: 8px;
}}
QPlainTextEdit:focus, QLineEdit:focus {{ border: 1px solid #a5bde4; }}
QLineEdit {{ selection-background-color: #536888; }}
QTextBrowser {{ selection-background-color: #67567d; }}
QScrollBar:vertical {{ background: transparent; width: 6px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #606c7a; border-radius: 2px; min-height: 24px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 6px; }}
QScrollBar::handle:horizontal {{ background: #606c7a; border-radius: 2px; min-width: 24px; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
QComboBox {{ background: #26313d; border: 1px solid #44515f; border-radius: 6px; padding: 5px 12px; }}
QComboBox QAbstractItemView {{ background: #26313d; selection-background-color: #40516b; }}
QListWidget, QTreeWidget {{ background: #232b34; border: none; outline: none; }}
QTreeWidget::item {{ padding: 8px 4px; }}
QTreeWidget::item:selected {{ background: #35465b; }}
QListWidget::item {{ padding: 10px 14px; border-radius: 8px; }}
QListWidget::item:selected {{ background: #35465b; color: #eaf0fa; }}
QListWidget::item:hover {{ background: #29394b; }}
QDialog, QMenu {{ background: #252d37; }}
QMenu {{ border: 1px solid #5b6980; padding: 6px; }}
QMenu::item {{ padding: 8px 22px; border-radius: 5px; }}
QMenu::item:selected {{ background: #435371; }}
QHeaderView::section {{ background: #252c34; color: #8fa2b5; padding: 8px; border: none; font-size: 10px; }}
QTableWidget {{ gridline-color: #39454e; selection-background-color: #344b51; border: none; background: transparent; }}
QTableWidget::item {{ padding: 8px; border-bottom: 1px solid #323d47; }}
QCheckBox {{ spacing: 7px; }}
QTabWidget::pane {{ border: 1px solid #3b4755; border-radius: 8px; }}
QTabBar::tab {{ background: #232b34; color: #a3b0c1; padding: 10px 16px; }}
QTabBar::tab:selected {{ background: #354252; color: #e9e8e4; }}
QToolTip {{ background: #253140; color: #eef2f7; border: 1px solid #71819c; padding: 6px; }}
"""

CANVAS_STYLE: Final = f"""
QWidget {{ color: {INK}; font-family: 'Segoe UI'; font-size: 13px; background: transparent; }}
QFrame#canvasPill {{ background: #25212f; border: 1px solid #494055; border-radius: 18px; }}
QLabel {{ background: transparent; border: none; }}
QLabel#muted {{ color: #a49aae; font-size: 11px; }}
QLabel#title {{ font-size: 14px; font-weight: 600; }}
QToolButton {{ border: 1px solid transparent; border-radius: 12px; padding: 5px 9px; background: transparent; }}
QToolButton:hover {{ background: #3a3148; }}
QToolButton:pressed {{ background: #4a3d5c; }}
QToolButton:checked {{ background: #3a3148; }}
QToolButton:focus {{ border-color: #ba9de3; }}
QToolButton:disabled {{ color: #70677d; }}
QToolButton#primary {{ background: {ACCENT}; color: #262131; font-weight: 600; padding: 7px 12px; }}
QToolButton#primary:hover {{ background: #e6d8fa; }}
QLineEdit, QPlainTextEdit, QComboBox {{ background: #211e29; border: 1px solid #4a405b; border-radius: 9px; padding: 7px; }}
QLineEdit:focus, QPlainTextEdit:focus {{ border-color: #b697df; }}
QPlainTextEdit:read-only {{ background: transparent; border: none; padding: 0; }}
QLineEdit#canvasSearch {{ background: transparent; border: none; padding: 5px 8px; }}
QComboBox QAbstractItemView {{ background: #292332; selection-background-color: #4a3a61; }}
QMenu {{ background: #292332; border: 1px solid #574968; padding: 7px; }}
QMenu::item {{ padding: 8px 20px; border-radius: 7px; }}
QMenu::item:selected {{ background: #443454; }}
QScrollBar:vertical {{ background: transparent; width: 5px; }}
QScrollBar::handle:vertical {{ background: #665372; border-radius: 2px; min-height: 20px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QToolTip {{ background: #292332; color: {INK}; border: 1px solid #675576; padding: 7px; }}
"""


@dataclass(frozen=True, slots=True)
class Ink:
    foreground: str = INK
    secondary: str = SECONDARY
    link: str = USER
    error: str = "#ffb7b2"


@dataclass(frozen=True, slots=True)
class Palette:
    surface: str
    edge: str
    accent: str
    tint: str


def palette(tone: Tone, app: App | None = None) -> Palette:
    match app:
        case App.TEAMS:
            return Palette("#292540", "#8076b2", "#d8d1ff", "#6655a0")
        case App.OUTLOOK:
            return Palette("#1d2c40", "#587fa7", "#c2e4ff", "#2869a2")
        case App.CODEX:
            return Palette("#222e31", "#68878b", "#d0eaeb", "#416f74")
        case App.CLAUDE:
            return Palette("#372922", "#a47c69", "#f4d2be", "#9c6049")
        case App.EDGE:
            return Palette("#203332", "#5e9690", "#c4f1e9", "#267e76")
        case App.WEB_PAGE:
            return Palette("#23313b", "#6e91a8", "#c6e4f3", "#456f88")
        case App.DOCUMENT:
            return Palette("#26312a", "#72967a", "#d2ead3", "#52795c")
        case App.KANBAN:
            return Palette("#332d25", "#9b8159", "#f1d5a2", "#816234")
        case App.WINDOWS:
            return Palette("#252c3a", "#6e83a5", "#d4e3ff", "#486a9c")
        case App.WORKSPACE | None:
            pass
        case _:
            assert_never(app)
    match tone:
        case Tone.USER | Tone.RECORDING:
            return Palette("#222c42", "#62738e", "#d3e3ff", "#335ba5")
        case Tone.THINKING | Tone.ACTION | Tone.REPLY:
            return Palette(SURFACE, EDGE, "#e8e1ff", "#4e4173")
        case Tone.QUESTION:
            return Palette(SURFACE, EDGE, "#f2ddb9", "#4e4173")
        case Tone.ERROR:
            return Palette(SURFACE, EDGE, "#ffb7b2", "#4e4173")
        case _:
            assert_never(tone)
