"""Workspace's colour tokens, bubble palettes and the Qt stylesheets generated from them.

Quiet blue and lilac glass, with opaque ink and a dark solid fallback.
"""

from dataclasses import dataclass
from typing import Final, assert_never

from assistant import island_model
from assistant.feed_origin import App
from assistant.island_model import Tint
from assistant.notifications import Tone
from winapi import appearance
from winapi.shapes import Stop, Veil

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


# Liquid Glass: glass has no colour of its own. Thin neutral veils carry
# monochrome ink; colour appears only where it means something.
GLASS_ACCENT: Final = "#4b8fe8"  # a soft blue, lighter and less saturated than system blue
ATTENTION: Final = "#f08a00"  # a question waits
RED: Final = "#ff453a"  # recording, low battery
MICROPHONE: Final = "#ff9f0a"  # the microphone is live, as Apple's privacy indicator


@dataclass(frozen=True, slots=True)
class Shade:
    color: str
    opacity: float = 1.0


@dataclass(frozen=True, slots=True)
class Lettering:
    """Ink for a surface: primary and quiet text, and the control fills under the pointer."""

    ink: Shade
    quiet: Shade
    hover: Shade
    press: Shade


@dataclass(frozen=True, slots=True)
class GlassLook:
    """Composition draws the veil; Qt paints only content and an invisible hit fill."""

    veil: Veil
    lettering: Lettering


@dataclass(frozen=True, slots=True)
class SolidLook:
    """No glass: Qt paints the whole surface."""

    fill: Shade
    edge: Shade
    lettering: Lettering


type Look = GlassLook | SolidLook


def _lettering(ink: str, *, dark: bool) -> Lettering:
    return Lettering(
        Shade(ink, 0.94 if dark else 0.86), Shade(ink, 0.58 if dark else 0.54), Shade(ink, 0.08 if dark else 0.06), Shade(ink, 0.14 if dark else 0.10)
    )


def _rim(high: float, low: float, end: float) -> tuple[Stop, ...]:
    """Brightest where light catches the upper-leading curve, a softer return at the trailing foot."""
    return (Stop(0, "#ffffff", high), Stop(0.34, "#ffffff", low), Stop(0.72, "#ffffff", low), Stop(1, "#ffffff", end))


def look(preference: appearance.Preference, frost: appearance.Frost, tint: Tint) -> Look:
    """Small glass takes its scheme from the desktop beneath it; a tint replaces the veil only for meaning."""
    match preference:
        case appearance.Contrast(background=background, foreground=foreground):
            # System colours, swapped when the capsule carries meaning.
            fill, ink = (foreground, background) if tint is Tint.ATTENTION else (background, foreground)
            return SolidLook(Shade(fill), Shade(ink), Lettering(Shade(ink), Shade(ink), Shade(ink, 0.2), Shade(ink, 0.35)))
        case appearance.Material.SOLID:
            match tint:
                case Tint.ATTENTION:
                    return SolidLook(Shade(ATTENTION), Shade("#ffffff", 0.18), _lettering("#ffffff", dark=True))
                case Tint.NONE:
                    return SolidLook(Shade("#26262a"), Shade("#ffffff", 0.07), _lettering("#ffffff", dark=True))
                case _:
                    assert_never(tint)
        case appearance.Material.GLASS:
            pass
        case _:
            assert_never(preference)
    bright = frost is appearance.Frost.BRIGHT
    shadow = 0.14 if bright else 0.36
    match tint:
        case Tint.ATTENTION:
            return GlassLook(Veil(ATTENTION, 0.9, _rim(0.55, 0.06, 0.10), shadow), _lettering("#ffffff", dark=True))
        case Tint.NONE:
            pass
        case _:
            assert_never(tint)
    match frost:
        case appearance.Frost.BRIGHT:
            return GlassLook(Veil("#ffffff", 0.2, _rim(0.95, 0.16, 0.42), shadow), _lettering("#000000", dark=False))
        case appearance.Frost.LIGHT:
            return GlassLook(Veil("#1c1c20", 0.26, _rim(0.55, 0.06, 0.22), shadow), _lettering("#ffffff", dark=True))
        case appearance.Frost.SMOKED:
            # A mixed desktop needs a heavier veil to keep small text legible.
            return GlassLook(Veil("#1c1c20", 0.62, _rim(0.55, 0.06, 0.22), shadow), _lettering("#ffffff", dark=True))
        case _:
            assert_never(frost)


def large(look: Look) -> Look:
    """Large glass is thicker, so a menu's text stays legible over any desktop."""
    match look:
        case GlassLook(veil=veil, lettering=lettering):
            return GlassLook(Veil(veil.tint, max(veil.opacity, 0.64), veil.rim, veil.shadow), lettering)
        case SolidLook():
            return look
        case _:
            assert_never(look)


def reading(lettering: Lettering, tone: island_model.Tone, *, contrast: bool) -> Shade:
    """A part's ink. High contrast keeps every reading in the system foreground."""
    if contrast:
        return lettering.ink
    match tone:
        case island_model.Tone.INK:
            return lettering.ink
        case island_model.Tone.QUIET:
            return lettering.quiet
        case island_model.Tone.MICROPHONE:
            return Shade(MICROPHONE)
        case island_model.Tone.LOW:
            return Shade(RED)
        case _:
            assert_never(tone)
