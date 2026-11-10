"""Workspace's Liquid Glass tokens and the Qt stylesheets generated from them.

Glass and content have no colour of their own: neutral surfaces and monochrome
ink in a dark and a light scheme, after the kit at JimLundin/liquid-glass.
Colour carries meaning only: the soft-blue accent for the primary action and
selection, orange for attention, red for recording and errors.
"""

from dataclasses import dataclass
from enum import Enum, auto
from functools import lru_cache
from typing import Final, assert_never

from contracts.members import every_member
from desktop_ui.components import typeface
from desktop_ui.components.meaning import Tint, Tone
from winapi import appearance
from winapi.shapes import Lighting, Stop

GLASS_ACCENT: Final = "#4b8fe8"  # a soft blue, lighter and less saturated than system blue
ATTENTION: Final = "#f08a00"  # something needs you
RED: Final = "#ff453a"  # recording, low battery, errors
MICROPHONE: Final = "#ff9f0a"  # the microphone is live, as Apple's privacy indicator
ON_ACCENT: Final = "#ffffff"  # ink and knobs over the accent or another signal hue


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


@dataclass(frozen=True, slots=True)
class Rim:
    """Rim light at the upper-leading curve, middle and trailing foot."""

    high: float
    low: float
    end: float


class Scheme(Enum):
    DARK = auto()
    LIGHT = auto()


@dataclass(frozen=True, slots=True, kw_only=True)
class Tokens:
    """One scheme's neutral surfaces and ink, and what its glass paints beyond them."""

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
    canvas_bar_veil: Shade
    """The veil behind Qt-painted glass."""
    rim: Rim
    segment: str
    """The checked choice in a segmented control."""


def scheme() -> Scheme:
    """Large glass and content windows follow Windows' app mode."""
    return Scheme.LIGHT if appearance.light_apps() else Scheme.DARK


@dataclass(frozen=True, slots=True)
class Padding:
    """Inside a control: above and below, and beside."""

    vertical: int
    horizontal: int

    def css(self, ring: int = 0) -> str:
        """The padding, less a focus ring's width on every side so the control keeps its size."""
        return f"padding: {self.vertical - ring}px {self.horizontal - ring}px;"


@dataclass(frozen=True, slots=True, kw_only=True)
class Kit:
    """The shared controls' metrics: every stylesheet number Workspace's windows use."""

    ring: int
    """A focused control's accent ring."""
    tooltip_radius: int
    tooltip: Padding
    button_radius: int
    button: Padding
    button_least: int
    """A button's least content height."""
    field_radius: int
    field: Padding
    item_radius: int
    item: Padding
    menu_radius: int
    menu_pad: int
    menu_item: Padding
    menu_separator: Padding
    """A menu separator's margin."""
    scrollbar: int
    scrollbar_along: int
    scrollbar_across: int
    """A scroll bar's margin along and across it."""
    thumb_radius: int
    thumb_least: int
    segmented_radius: int
    segmented_inset: int
    """Between the segmented well and its choices, and between choices."""
    choice_radius: int
    choice: Padding
    choice_least: int
    hairline: int
    """A surface's and a menu's edge."""


KIT: Final = Kit(
    ring=2,
    tooltip_radius=8,
    tooltip=Padding(5, 8),
    button_radius=14,
    button=Padding(5, 11),
    button_least=18,
    field_radius=10,
    field=Padding(7, 10),
    item_radius=15,
    item=Padding(8, 12),
    menu_radius=12,
    menu_pad=6,
    menu_item=Padding(6, 14),
    menu_separator=Padding(5, 10),
    scrollbar=8,
    scrollbar_along=4,
    scrollbar_across=2,
    thumb_radius=3,
    thumb_least=24,
    segmented_radius=10,
    segmented_inset=2,
    choice_radius=8,
    choice=Padding(4, 12),
    choice_least=18,
    hairline=1,
)
"""Workspace's control metrics; owners pass them to the stylesheets."""


def tooltip_style(theme: Tokens, kit: Kit) -> str:
    """Tooltips, the one rule the process shares: every other control takes its look from the window that owns it."""
    line, edge = theme.separator.css, kit.hairline
    return (
        f"QToolTip {{ background: {theme.solid}; color: {theme.ink.css}; border: {edge}px solid {line}; "
        f"border-radius: {kit.tooltip_radius}px; {kit.tooltip.css()} }}\n"
    )


def control_style(theme: Tokens, kit: Kit) -> str:
    """Workspace's dialogs and controls: Inter, capsule buttons, quiet wells and overlay scroll bars."""
    ink, ink2, ink3 = theme.ink.css, theme.ink2.css, theme.ink3.css
    fill, hover, press, line = theme.fill.css, theme.hover.css, theme.press.css, theme.separator.css
    weight, ring, edge = int(typeface.TYPE.title.weight), kit.ring, kit.hairline
    along, across = kit.scrollbar_along, kit.scrollbar_across
    return f"""
QWidget {{ color: {ink}; font-family: '{typeface.FAMILY}'; {typeface.TYPE.body.css} }}
QDialog {{ background: {theme.window}; }}
QLabel {{ background: transparent; border: none; }}
QLabel#muted {{ color: {ink2}; {typeface.TYPE.detail.css} }}
QToolButton {{
 border: none; border-radius: {kit.button_radius}px; background: transparent; {kit.button.css()}
 font-weight: {weight}; min-height: {kit.button_least}px;
}}
QToolButton:hover {{ background: {hover}; }}
QToolButton:pressed {{ background: {press}; }}
QToolButton:focus {{ outline: none; border: {ring}px solid {GLASS_ACCENT}; {kit.button.css(ring)} }}
QToolButton:disabled {{ color: {ink3}; }}
QToolButton:checked {{ background: {hover}; }}
QLineEdit {{
 background: {fill}; border: none; border-radius: {kit.field_radius}px; {kit.field.css()}
 selection-background-color: {GLASS_ACCENT}; selection-color: {ON_ACCENT};
}}
QLineEdit:focus {{ border: {ring}px solid {GLASS_ACCENT}; {kit.field.css(ring)} }}
QListWidget {{ background: transparent; border: none; outline: none; }}
QListWidget::item {{ {kit.item.css()} border-radius: {kit.item_radius}px; }}
QListWidget::item:hover {{ background: {hover}; }}
QListWidget::item:selected {{ background: {GLASS_ACCENT}; color: {ON_ACCENT}; }}
QMenu {{ background: {theme.solid}; border: {edge}px solid {line}; border-radius: {kit.menu_radius}px; padding: {kit.menu_pad}px; }}
QMenu::item {{ {kit.menu_item.css()} border-radius: {kit.item_radius}px; }}
QMenu::item:selected {{ background: {GLASS_ACCENT}; color: {ON_ACCENT}; }}
QMenu::separator {{
 height: {edge}px; background: {line}; margin: {kit.menu_separator.vertical}px {kit.menu_separator.horizontal}px;
}}
QScrollBar:vertical {{ background: transparent; width: {kit.scrollbar}px; margin: {along}px {across}px; }}
QScrollBar::handle:vertical {{ background: {theme.thumb.css}; border-radius: {kit.thumb_radius}px; min-height: {kit.thumb_least}px; }}
QScrollBar:horizontal {{ background: transparent; height: {kit.scrollbar}px; margin: {across}px {along}px; }}
QScrollBar::handle:horizontal {{ background: {theme.thumb.css}; border-radius: {kit.thumb_radius}px; min-width: {kit.thumb_least}px; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ width: 0; height: 0; background: transparent; }}
""" + tooltip_style(theme, kit)


# Every glass surface shares its ink and rim vocabulary.
@dataclass(frozen=True, slots=True)
class Lettering:
    """Ink for a surface: primary and quiet text, and the control fills under the pointer."""

    ink: Shade
    quiet: Shade
    hover: Shade
    press: Shade


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
class CanvasBar:
    """Qt-painted glass is thicker over the canvas's content scheme."""

    scheme: Scheme


type Pane = Capsule | Menu | CanvasBar


def lettering(theme: Tokens) -> Lettering:
    """The surface's text and pointer fills come from its scheme's tokens."""
    return Lettering(theme.ink, theme.ink2, theme.hover, theme.press)


@dataclass(frozen=True, slots=True)
class FrostLook:
    """How glass reads over a desktop of this frost: its scheme, the veil behind small text, and its shadow's strength."""

    scheme: Scheme
    """A glass capsule or menu's scheme follows the desktop behind it."""
    small_veil: Shade
    shadow: float


@dataclass(frozen=True, slots=True, kw_only=True)
class Attention:
    """A surface that needs you: the attention hue's veil, its own rim and white lettering."""

    hue: str
    veil: float
    """The veil's opacity over the desktop..."""
    canvas_veil: float
    """...and over Qt-painted glass."""
    rim: Rim
    lettering: Lettering
    solid_edge: Shade


@dataclass(frozen=True, slots=True, kw_only=True)
class Glass:
    """Workspace's whole material recipe: each scheme's tokens, how glass reads over each frost, and attention."""

    tokens: frozendict[Scheme, Tokens]
    frosts: frozendict[appearance.Frost, FrostLook]
    attention: Attention
    menu_veil: float
    """The least an expanded menu's veil may be, so its text keeps its contrast."""
    contrast_hover: float
    contrast_press: float
    """High contrast's pointer feedback: the system foreground at these opacities."""
    lighting: Lighting
    rim_light: str
    rim_fall: float
    """Where the rim has fallen from its high at the upper-leading curve..."""
    rim_rise: float
    """...and where it starts rising again towards the trailing foot."""

    def __post_init__(self) -> None:
        every_member(Scheme, self.tokens)
        every_member(appearance.Frost, self.frosts)


def rim_stops(rim: Rim, glass: Glass) -> tuple[Stop, ...]:
    """Brightest where light catches the upper-leading curve, a softer return at the trailing foot."""
    light = glass.rim_light
    return (Stop(0, light, rim.high), Stop(glass.rim_fall, light, rim.low), Stop(glass.rim_rise, light, rim.low), Stop(1, light, rim.end))


_WHITE, _BLACK = "#ffffff", "#000000"

GLASS: Final = Glass(
    tokens=every_member(
        Scheme,
        {
            Scheme.DARK: Tokens(
                scheme=Scheme.DARK,
                ink=Shade(_WHITE, 0.94),
                ink2=Shade(_WHITE, 0.58),
                ink3=Shade(_WHITE, 0.30),
                fill=Shade(_WHITE, 0.06),
                hover=Shade(_WHITE, 0.08),
                press=Shade(_WHITE, 0.14),
                separator=Shade(_WHITE, 0.12),
                solid="#26262a",
                solid_edge=Shade(_WHITE, 0.07),
                window="#161618",
                thumb=Shade(_WHITE, 0.40),
                canvas_bar_veil=Shade("#1e1e22", 0.84),
                rim=Rim(0.55, 0.06, 0.22),
                segment="rgba(255,255,255,56)",
            ),
            Scheme.LIGHT: Tokens(
                scheme=Scheme.LIGHT,
                ink=Shade(_BLACK, 0.86),
                ink2=Shade(_BLACK, 0.54),
                ink3=Shade(_BLACK, 0.28),
                fill=Shade(_BLACK, 0.05),
                hover=Shade(_BLACK, 0.06),
                press=Shade(_BLACK, 0.10),
                separator=Shade(_BLACK, 0.10),
                solid="#ffffff",
                solid_edge=Shade(_BLACK, 0.07),
                window="#f3f3f6",
                thumb=Shade(_BLACK, 0.36),
                canvas_bar_veil=Shade("#fbfbfd", 0.86),
                rim=Rim(0.95, 0.16, 0.42),
                segment="#ffffff",
            ),
        },
    ),
    frosts=every_member(
        appearance.Frost,
        {
            appearance.Frost.BRIGHT: FrostLook(Scheme.LIGHT, Shade(_WHITE, 0.2), 0.14),
            appearance.Frost.LIGHT: FrostLook(Scheme.DARK, Shade("#1c1c20", 0.26), 0.36),
            # A mixed desktop needs a heavier veil to keep small text legible.
            appearance.Frost.SMOKED: FrostLook(Scheme.DARK, Shade("#1c1c20", 0.62), 0.36),
        },
    ),
    attention=Attention(
        hue=ATTENTION,
        veil=0.9,
        canvas_veil=0.94,
        rim=Rim(0.55, 0.06, 0.10),
        lettering=Lettering(Shade(_WHITE, 0.96), Shade(_WHITE, 0.8), Shade(_WHITE, 0.16), Shade(_WHITE, 0.26)),
        solid_edge=Shade(_WHITE, 0.18),
    ),
    menu_veil=0.64,
    contrast_hover=0.2,
    contrast_press=0.35,
    lighting=Lighting(shadow_blur=24, shadow_drop=8, shadow_color=_BLACK, rim_stroke=2, rim_angle=160),
    rim_light=_WHITE,
    rim_fall=0.34,
    rim_rise=0.72,
)
"""Workspace's material; owners pass it in, tests pass their own."""


def tokens(scheme: Scheme) -> Tokens:
    """Workspace's own tokens for a window's scheme, for the owners that build windows."""
    return GLASS.tokens[scheme]


@dataclass(frozen=True, slots=True, kw_only=True)
class Washes:
    """A surface's ink at lower opacities, for wells and quiet marks drawn in it."""

    well: float
    """A tile's well."""
    off: float
    """A setting's symbol circle while it is off."""
    track: float
    """A slider's empty track."""
    halo: float
    """The glow around a signal's dot."""
    resting: float
    """A pulsing dot between pulses."""


WASHES: Final = Washes(well=0.07, off=0.12, track=0.16, halo=0.25, resting=0.35)


def _scheme(pane: Pane, material: appearance.Material, glass: Glass) -> Scheme:
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
            return glass.frosts[frost].scheme
        case CanvasBar(scheme=scheme):
            return scheme
        case _:
            assert_never(pane)


def _veil(pane: Pane, glass: Glass) -> Shade:
    match pane:
        case Capsule(frost=frost):
            return glass.frosts[frost].small_veil
        case Menu(frost=frost):
            small = glass.frosts[frost].small_veil
            return Shade(small.color, max(small.opacity, glass.menu_veil))
        case CanvasBar(scheme=scheme):
            return glass.tokens[scheme].canvas_bar_veil
        case _:
            assert_never(pane)


def _attention(pane: Pane, attention: Attention) -> GlassLook:
    match pane:
        case CanvasBar():
            return GlassLook(Shade(attention.hue, attention.canvas_veil), attention.rim, attention.lettering)
        case Capsule() | Menu():
            return GlassLook(Shade(attention.hue, attention.veil), attention.rim, attention.lettering)
        case _:
            assert_never(pane)


@lru_cache(maxsize=32)  # Every frame asks again for each capsule; the answers are a handful of values.
def look(preference: appearance.Preference, pane: Pane, tint: Tint, glass: Glass) -> Look:
    """One material recipe; pane ownership selects the scheme and veil thickness."""
    match preference:
        case appearance.Contrast(background=background, foreground=foreground):
            # System colours, swapped when the surface carries meaning.
            fill, ink = (foreground, background) if tint is Tint.ATTENTION else (background, foreground)
            feedback = Lettering(Shade(ink), Shade(ink), Shade(ink, glass.contrast_hover), Shade(ink, glass.contrast_press))
            return SolidLook(Shade(fill), Shade(ink), feedback)
        case appearance.Material.SOLID:
            match tint:
                case Tint.ATTENTION:
                    attention = glass.attention
                    return SolidLook(Shade(attention.hue), attention.solid_edge, attention.lettering)
                case Tint.NONE:
                    theme = glass.tokens[_scheme(pane, appearance.Material.SOLID, glass)]
                    return SolidLook(Shade(theme.solid), theme.solid_edge, lettering(theme))
                case _:
                    assert_never(tint)
        case appearance.Material.GLASS:
            pass
        case _:
            assert_never(preference)
    match tint:
        case Tint.ATTENTION:
            return _attention(pane, glass.attention)
        case Tint.NONE:
            pass
        case _:
            assert_never(tint)
    theme = glass.tokens[_scheme(pane, appearance.Material.GLASS, glass)]
    return GlassLook(_veil(pane, glass), theme.rim, lettering(theme))


def reading(lettering: Lettering, tone: Tone, *, contrast: bool) -> Shade:
    """A part's ink. High contrast keeps every reading in the system foreground."""
    if contrast:
        return lettering.ink
    match tone:
        case Tone.INK:
            return lettering.ink
        case Tone.MICROPHONE:
            return Shade(MICROPHONE)
        case Tone.LOW:
            return Shade(RED)
        case _:
            assert_never(tone)
