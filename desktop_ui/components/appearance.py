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

from contracts.members import every_member
from desktop_ui.components import typeface
from desktop_ui.components.meaning import Tint, Tone
from winapi import appearance
from winapi.shapes import Stop

GLASS_ACCENT: Final = "#4b8fe8"  # a soft blue, lighter and less saturated than system blue
ATTENTION: Final = "#f08a00"  # a question waits
RED: Final = "#ff453a"  # recording, low battery, errors
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


def tooltip_style(theme: Tokens) -> str:
    """Tooltips, the one rule the process shares: every other control takes its look from the window that owns it."""
    line = theme.separator.css
    return f"QToolTip {{ background: {theme.solid}; color: {theme.ink.css}; border: 1px solid {line}; border-radius: 8px; padding: 5px 8px; }}\n"


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
""" + tooltip_style(theme)


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
""" + tooltip_style(theme)


# Every glass surface shares its ink and rim vocabulary.
@dataclass(frozen=True, slots=True)
class Lettering:
    """Ink for a surface: primary and quiet text, and the control fills under the pointer."""

    ink: Shade
    quiet: Shade
    hover: Shade
    press: Shade


@dataclass(frozen=True, slots=True)
class Rim:
    """Rim light at the upper-leading curve, middle and trailing foot."""

    high: float
    low: float
    end: float


@dataclass(frozen=True, slots=True)
class GlassLook:
    """A veil and rim for composition or Qt, with the same surface lettering."""

    veil: Shade
    rim: Rim
    lettering: Lettering


@dataclass(frozen=True, slots=True)
class SolidLook:
    """No glass: Qt paints the whole surface."""

    fill: Shade
    edge: Shade
    lettering: Lettering


type Look = GlassLook | SolidLook


@dataclass(frozen=True, slots=True)
class Capsule:
    """Small desktop glass follows the observed background."""

    frost: appearance.Frost


@dataclass(frozen=True, slots=True)
class Menu:
    """Expanded desktop glass is thicker over the same observed background."""

    frost: appearance.Frost


@dataclass(frozen=True, slots=True)
class Card:
    """Large desktop glass follows the app scheme."""

    scheme: Scheme


@dataclass(frozen=True, slots=True)
class CanvasBar:
    """Qt-painted glass is thicker over the canvas's content scheme."""

    scheme: Scheme


type Pane = Capsule | Menu | Card | CanvasBar


def lettering(theme: Tokens) -> Lettering:
    """The surface's text and pointer fills come from its scheme's tokens."""
    return Lettering(theme.ink, theme.ink2, theme.hover, theme.press)


def rim_stops(rim: Rim) -> tuple[Stop, ...]:
    """Brightest where light catches the upper-leading curve, a softer return at the trailing foot."""
    return (Stop(0, "#ffffff", rim.high), Stop(0.34, "#ffffff", rim.low), Stop(0.72, "#ffffff", rim.low), Stop(1, "#ffffff", rim.end))


@dataclass(frozen=True, slots=True)
class FrostLook:
    """How glass reads over a desktop of this frost: its scheme, the veil behind small text, and its shadow's strength."""

    scheme: Scheme
    """A glass capsule or menu's scheme follows the desktop behind it."""
    small_veil: Shade
    shadow: float


FROSTS: Final = every_member(
    appearance.Frost,
    {
        appearance.Frost.BRIGHT: FrostLook(Scheme.LIGHT, Shade("#ffffff", 0.2), 0.14),
        appearance.Frost.LIGHT: FrostLook(Scheme.DARK, Shade("#1c1c20", 0.26), 0.36),
        # A mixed desktop needs a heavier veil to keep small text legible.
        appearance.Frost.SMOKED: FrostLook(Scheme.DARK, Shade("#1c1c20", 0.62), 0.36),
    },
)
CARD_VEILS: Final = every_member(Scheme, {Scheme.DARK: Shade("#222226", 0.64), Scheme.LIGHT: Shade("#fafafc", 0.66)})
CANVAS_BAR_VEILS: Final = every_member(Scheme, {Scheme.DARK: Shade("#1e1e22", 0.84), Scheme.LIGHT: Shade("#fbfbfd", 0.86)})
GLASS_RIMS: Final = every_member(Scheme, {Scheme.DARK: Rim(0.55, 0.06, 0.22), Scheme.LIGHT: Rim(0.95, 0.16, 0.42)})


def _scheme(pane: Pane, material: appearance.Material) -> Scheme:
    match pane:
        case Capsule(frost=frost) | Menu(frost=frost):
            match material:
                case appearance.Material.SOLID:
                    # The bar's solid fallback stays dark regardless of desktop frost.
                    return Scheme.DARK
                case appearance.Material.GLASS:
                    pass
                case _:
                    assert_never(material)
            return FROSTS[frost].scheme
        case Card(scheme=scheme) | CanvasBar(scheme=scheme):
            return scheme
        case _:
            assert_never(pane)


def _veil(pane: Pane) -> Shade:
    match pane:
        case Capsule(frost=frost):
            return FROSTS[frost].small_veil
        case Menu(frost=frost):
            small = FROSTS[frost].small_veil
            return Shade(small.color, max(small.opacity, 0.64))
        case Card(scheme=scheme):
            return CARD_VEILS[scheme]
        case CanvasBar(scheme=scheme):
            return CANVAS_BAR_VEILS[scheme]
        case _:
            assert_never(pane)


def _attention(pane: Pane) -> GlassLook:
    rim = Rim(0.55, 0.06, 0.10)
    white = "#ffffff"
    ink = Lettering(Shade(white, 0.96), Shade(white, 0.8), Shade(white, 0.16), Shade(white, 0.26))
    match pane:
        case CanvasBar():
            return GlassLook(Shade(ATTENTION, 0.94), rim, ink)
        case Capsule() | Menu() | Card():
            return GlassLook(Shade(ATTENTION, 0.9), rim, ink)
        case _:
            assert_never(pane)


@lru_cache(maxsize=32)  # Every frame asks again for each capsule; the answers are a handful of values.
def look(preference: appearance.Preference, pane: Pane, tint: Tint) -> Look:
    """One material recipe; pane ownership selects the scheme and veil thickness."""
    match preference:
        case appearance.Contrast(background=background, foreground=foreground):
            # System colours, swapped when the surface carries meaning.
            fill, ink = (foreground, background) if tint is Tint.ATTENTION else (background, foreground)
            return SolidLook(Shade(fill), Shade(ink), Lettering(Shade(ink), Shade(ink), Shade(ink, 0.2), Shade(ink, 0.35)))
        case appearance.Material.SOLID:
            match tint:
                case Tint.ATTENTION:
                    return SolidLook(Shade(ATTENTION), Shade("#ffffff", 0.18), _attention(pane).lettering)
                case Tint.NONE:
                    theme = tokens(_scheme(pane, appearance.Material.SOLID))
                    return SolidLook(Shade(theme.solid), theme.solid_edge, lettering(theme))
                case _:
                    assert_never(tint)
        case appearance.Material.GLASS:
            pass
        case _:
            assert_never(preference)
    match tint:
        case Tint.ATTENTION:
            return _attention(pane)
        case Tint.NONE:
            pass
        case _:
            assert_never(tint)
    scheme = _scheme(pane, appearance.Material.GLASS)
    return GlassLook(_veil(pane), GLASS_RIMS[scheme], lettering(tokens(scheme)))


def reading(lettering: Lettering, tone: Tone, *, contrast: bool) -> Shade:
    """A part's ink. High contrast keeps every reading in the system foreground."""
    if contrast:
        return lettering.ink
    match tone:
        case Tone.INK:
            return lettering.ink
        case Tone.QUIET:
            return lettering.quiet
        case Tone.MICROPHONE:
            return Shade(MICROPHONE)
        case Tone.LOW:
            return Shade(RED)
        case _:
            assert_never(tone)
