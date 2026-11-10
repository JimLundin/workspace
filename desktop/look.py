"""How Workspace's windows read: the colours that carry meaning, the glass and its
schemes, the controls' metrics and the type scale. Only declarations, in the
shapes `desktop_ui.components` declares; `desktop.__main__` hands them to the desktop.
"""

from typing import Final

from contracts.members import every_member
from desktop_ui.components.appearance import Attention, Design, FrostLook, Glass, Kit, Lettering, Padding, Palette, Rim, Scheme, Shade, Tokens, Washes
from desktop_ui.components.typeface import Font, TypeScale, Weight
from winapi import appearance
from winapi.shapes import Lighting

PALETTE: Final = Palette(
    accent="#4b8fe8",  # a soft blue, lighter and less saturated than system blue
    attention="#f08a00",
    red="#ff453a",
    microphone="#ff9f0a",  # as Apple's privacy indicator
    on_accent="#ffffff",
)


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
        hue=PALETTE.attention,
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


WASHES: Final = Washes(well=0.07, off=0.12, track=0.16, halo=0.25, resting=0.35)


TYPE: Final = TypeScale(
    reading=Font(12, Weight.MEDIUM, tabular=True),
    strong=Font(12, Weight.SEMIBOLD, tabular=True),
    detail=Font(11, Weight.REGULAR),
    body=Font(13, Weight.REGULAR),
    title=Font(13, Weight.MEDIUM),
    label=Font(12, Weight.MEDIUM),
    query=Font(19, Weight.REGULAR),
    keycap_name=Font(10, Weight.REGULAR),
    keycap=Font(15, Weight.SEMIBOLD),
    keycap_long=Font(12, Weight.SEMIBOLD),
)
"""Workspace's type scale; each surface reads its sizes from here or from what its owner passes in."""


DESIGN: Final = Design(palette=PALETTE, glass=GLASS, kit=KIT, type=TYPE)
"""The look every window is handed."""
