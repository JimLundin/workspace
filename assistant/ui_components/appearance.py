"""Workspace's Liquid Glass tokens and the Qt stylesheets generated from them.

Glass and content have no colour of their own: neutral surfaces and monochrome
ink in a dark and a light scheme, after the kit at JimLundin/liquid-glass.
Colour carries meaning only: the soft-blue accent for the primary action and
selection, orange for a question, red for recording and errors, and each app's
own colour on its badge.
"""

from dataclasses import dataclass
from enum import Enum, auto
from functools import lru_cache
from typing import Final, assert_never

from assistant import island_model
from assistant.feed_origin import App
from assistant.island_model import Tint
from assistant.notifications import Tone
from assistant.ui_components import typeface
from winapi import appearance
from winapi.shapes import Stop, Veil

GLASS_ACCENT: Final = "#4b8fe8"  # a soft blue, lighter and less saturated than system blue
ATTENTION: Final = "#f08a00"  # a question waits
RED: Final = "#ff453a"  # recording, low battery, errors
GREEN: Final = "#30d158"  # switches, success
MICROPHONE: Final = "#ff9f0a"  # the microphone is live, as Apple's privacy indicator


@dataclass(frozen=True, slots=True)
class Shade:
    color: str
    opacity: float = 1.0

    @property
    def css(self) -> str:
        """For Qt stylesheets, which take rgba() but not #AARRGGBB."""
        red, green, blue = (int(self.color[index : index + 2], 16) for index in (1, 3, 5))
        return f"rgba({red},{green},{blue},{round(self.opacity * 255)})"

    @property
    def argb(self) -> str:
        """For QColor."""
        return f"#{round(self.opacity * 255):02x}{self.color[1:]}"


class Scheme(Enum):
    DARK = auto()
    LIGHT = auto()


@dataclass(frozen=True, slots=True)
class Tokens:
    """One scheme's neutral surfaces and ink."""

    scheme: Scheme
    ink: Shade
    ink2: Shade  # secondary text, symbols beside text
    ink3: Shade  # tertiary text, placeholders, shortcut hints
    fill: Shade  # a quiet well inside a surface
    hover: Shade
    press: Shade
    separator: Shade
    solid: str  # a content card
    solid_edge: Shade
    window: str  # a content window's background
    thumb: Shade  # overlay scroll bars


def tokens(scheme: Scheme) -> Tokens:
    match scheme:
        case Scheme.DARK:
            white = "#ffffff"
            return Tokens(
                scheme, Shade(white, 0.94), Shade(white, 0.58), Shade(white, 0.30), Shade(white, 0.06), Shade(white, 0.08), Shade(white, 0.14),
                Shade(white, 0.12), "#26262a", Shade(white, 0.07), "#161618", Shade(white, 0.40),
            )  # fmt: skip
        case Scheme.LIGHT:
            black = "#000000"
            return Tokens(
                scheme, Shade(black, 0.86), Shade(black, 0.54), Shade(black, 0.28), Shade(black, 0.05), Shade(black, 0.06), Shade(black, 0.10),
                Shade(black, 0.10), "#ffffff", Shade(black, 0.07), "#f3f3f6", Shade(black, 0.36),
            )  # fmt: skip
        case _:
            assert_never(scheme)


DARK: Final = tokens(Scheme.DARK)


def scheme() -> Scheme:
    """Large glass and content windows follow Windows' app mode."""
    return Scheme.LIGHT if appearance.light_apps() else Scheme.DARK


def control_style(theme: Tokens) -> str:
    """Workspace's dialogs and controls: Inter, capsule buttons, quiet wells and overlay scroll bars."""
    ink, ink2, ink3 = theme.ink.css, theme.ink2.css, theme.ink3.css
    fill, hover, press, line = theme.fill.css, theme.hover.css, theme.press.css, theme.separator.css
    return f"""
QWidget {{ color: {ink}; font-family: '{typeface.FAMILY}'; font-size: 13px; }}
QDialog, QMainWindow {{ background: {theme.window}; }}
QLabel {{ background: transparent; border: none; }}
QLabel#muted {{ color: {ink2}; font-size: 11px; }}
QLabel#title {{ font-size: 15px; font-weight: 600; }}
QLabel#status {{ color: {ATTENTION}; font-size: 11px; }}
QToolButton, QPushButton {{ border: none; border-radius: 14px; background: transparent; padding: 5px 11px; font-weight: 500; min-height: 18px; }}
QToolButton:hover, QPushButton:hover {{ background: {hover}; }}
QToolButton:pressed, QPushButton:pressed {{ background: {press}; }}
QToolButton:focus, QPushButton:focus {{ outline: none; border: 2px solid {GLASS_ACCENT}; padding: 3px 9px; }}
QToolButton:disabled, QPushButton:disabled {{ color: {ink3}; }}
QToolButton:checked {{ background: {hover}; }}
QToolButton#primary, QPushButton#primary {{ background: {GLASS_ACCENT}; color: #ffffff; font-weight: 600; }}
QToolButton#primary:hover, QPushButton#primary:hover {{ background: #6aa2ec; }}
QToolButton#chip {{ background: {fill}; border-radius: 10px; padding: 2px 8px; font-size: 11px; }}
QLineEdit, QPlainTextEdit, QTextBrowser, QComboBox {{
 background: {fill}; border: none; border-radius: 10px; padding: 7px 10px; selection-background-color: {GLASS_ACCENT}; selection-color: #ffffff;
}}
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus {{ border: 2px solid {GLASS_ACCENT}; padding: 5px 8px; }}
QComboBox QAbstractItemView {{ background: {theme.solid}; border: none; selection-background-color: {GLASS_ACCENT}; selection-color: #ffffff; }}
QTableWidget {{ background: transparent; border: none; gridline-color: {line}; selection-background-color: {fill}; }}
QTableWidget::item {{ padding: 7px; border-bottom: 1px solid {line}; }}
QHeaderView::section {{ background: transparent; color: {ink2}; padding: 7px; border: none; font-size: 11px; font-weight: 600; }}
QListWidget, QTreeWidget {{ background: transparent; border: none; outline: none; }}
QListWidget::item, QTreeWidget::item {{ padding: 8px 12px; border-radius: 15px; }}
QListWidget::item:hover, QTreeWidget::item:hover {{ background: {hover}; }}
QListWidget::item:selected, QTreeWidget::item:selected {{ background: {GLASS_ACCENT}; color: #ffffff; }}
QMenu {{ background: {theme.solid}; border: 1px solid {line}; border-radius: 12px; padding: 6px; }}
QMenu::item {{ padding: 6px 14px; border-radius: 15px; }}
QMenu::item:selected {{ background: {GLASS_ACCENT}; color: #ffffff; }}
QMenu::separator {{ height: 1px; background: {line}; margin: 5px 10px; }}
QCheckBox {{ spacing: 8px; }}
QTabWidget::pane {{ border: none; }}
QTabBar::tab {{ background: transparent; color: {ink2}; padding: 6px 14px; border-radius: 14px; margin: 2px; }}
QTabBar::tab:selected {{ background: {hover}; color: {ink}; }}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 4px 2px; }}
QScrollBar::handle:vertical {{ background: {theme.thumb.css}; border-radius: 3px; min-height: 24px; }}
QScrollBar:horizontal {{ background: transparent; height: 8px; margin: 2px 4px; }}
QScrollBar::handle:horizontal {{ background: {theme.thumb.css}; border-radius: 3px; min-width: 24px; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ width: 0; height: 0; background: transparent; }}
QToolTip {{ background: {theme.solid}; color: {ink}; border: 1px solid {line}; border-radius: 8px; padding: 5px 8px; }}
"""


def canvas_style(theme: Tokens) -> str:
    """The canvas: a solid content window; its toolbars and inspector carry the floating controls."""
    ink2, fill, hover, press, line = theme.ink2.css, theme.fill.css, theme.hover.css, theme.press.css, theme.separator.css
    return f"""
QWidget {{ color: {theme.ink.css}; font-family: '{typeface.FAMILY}'; font-size: 13px; background: transparent; }}
QFrame#canvasPill {{ background: {theme.solid}; border: 1px solid {theme.solid_edge.css}; border-radius: 18px; }}
QLabel {{ background: transparent; border: none; }}
QLabel#muted {{ color: {ink2}; font-size: 11.5px; }}
QLabel#title {{ font-size: 14px; font-weight: 600; }}
QToolButton {{ border: none; border-radius: 14px; padding: 5px 11px; background: transparent; font-weight: 500; }}
QToolButton:hover {{ background: {hover}; }}
QToolButton:pressed {{ background: {press}; }}
QToolButton:checked {{ background: {hover}; }}
QToolButton:focus {{ border: 2px solid {GLASS_ACCENT}; padding: 3px 9px; }}
QToolButton:disabled {{ color: {theme.ink3.css}; }}
QToolButton#primary {{ background: {GLASS_ACCENT}; color: #ffffff; font-weight: 600; }}
QToolButton#primary:hover {{ background: #6aa2ec; }}
QLineEdit, QPlainTextEdit, QComboBox {{
 background: {fill}; border: none; border-radius: 10px; padding: 7px 10px; selection-background-color: {GLASS_ACCENT};
}}
QLineEdit:focus, QPlainTextEdit:focus {{ border: 2px solid {GLASS_ACCENT}; padding: 5px 8px; }}
QPlainTextEdit:read-only {{ background: transparent; border: none; padding: 0; }}
QLineEdit#canvasSearch {{ background: transparent; border: none; padding: 5px 8px; }}
QComboBox QAbstractItemView {{ background: {theme.solid}; selection-background-color: {GLASS_ACCENT}; }}
QMenu {{ background: {theme.solid}; border: 1px solid {line}; border-radius: 12px; padding: 6px; }}
QMenu::item {{ padding: 6px 14px; border-radius: 15px; }}
QMenu::item:selected {{ background: {GLASS_ACCENT}; color: #ffffff; }}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 4px 2px; }}
QScrollBar::handle:vertical {{ background: {theme.thumb.css}; border-radius: 3px; min-height: 20px; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ height: 0; width: 0; background: transparent; }}
QToolTip {{ background: {theme.solid}; color: {theme.ink.css}; border: 1px solid {line}; border-radius: 8px; padding: 5px 8px; }}
"""


# Migration: these names carry the dark scheme until each surface reads its tokens.
ACCENT: Final = GLASS_ACCENT
INK: Final = "#f0f0f0"
SECONDARY: Final = "#a1a1a4"
USER: Final = "#8fb7ef"
SURFACE: Final = DARK.solid
EDGE: Final = "#3a3a3e"
OVERLAY_BACKGROUND: Final = DARK.window
OVERLAY_INK: Final = INK
OVERLAY_MUTED: Final = SECONDARY
OVERLAY_ACCENT: Final = GLASS_ACCENT
OVERLAY_SURFACE: Final = DARK.solid
CONTROL_STYLE: Final = control_style(DARK)
CANVAS_STYLE: Final = canvas_style(DARK)


@dataclass(frozen=True, slots=True)
class Ink:
    foreground: str = INK
    secondary: str = SECONDARY
    link: str = USER
    error: str = "#ff8a80"


@dataclass(frozen=True, slots=True)
class Palette:
    """A card: neutral surface and edge; `accent` is its meaning or its app's colour, for the badge."""

    surface: str
    edge: str
    accent: str
    tint: str


def brand(app: App) -> str:
    """Each app's own colour, shown only on its badge."""
    match app:
        case App.TEAMS:
            return "#6264a7"
        case App.OUTLOOK:
            return "#0f6cbd"
        case App.CODEX:
            return "#10a37f"
        case App.CLAUDE:
            return "#d97757"
        case App.EDGE:
            return "#1b9de2"
        case App.WEB_PAGE:
            return "#5e9ad6"
        case App.DOCUMENT:
            return "#2b7cd3"
        case App.KANBAN:
            return "#c28a2c"
        case App.WINDOWS:
            return "#0078d4"
        case App.WORKSPACE:
            return GLASS_ACCENT
        case _:
            assert_never(app)


def palette(tone: Tone, app: App | None = None) -> Palette:
    neutral = (SURFACE, EDGE)
    if app is not None:
        return Palette(*neutral, brand(app), "#1c1c20")
    match tone:
        case Tone.USER | Tone.RECORDING | Tone.THINKING | Tone.ACTION | Tone.REPLY:
            return Palette(*neutral, GLASS_ACCENT, "#1c1c20")
        case Tone.QUESTION:
            return Palette(*neutral, ATTENTION, "#1c1c20")
        case Tone.ERROR:
            return Palette(*neutral, RED, "#1c1c20")
        case _:
            assert_never(tone)


# Small glass: thin neutral veils with monochrome ink.
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


@lru_cache(maxsize=32)  # Every frame asks again for each capsule; the answers are a handful of values.
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


@lru_cache(maxsize=16)
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
