"""The island bar's geometry, in device-independent pixels.

Every size the bar lays out and paints is here, so a change applies everywhere
the value is used.
"""

from typing import Final

from desktop_ui.ui_spec import Bar, Capsule, Detail, MenuGrid, Sizes

SIZES: Final = Sizes(
    bar=Bar(top=8, edge=12, gap=6, radius=17, shadow=40),
    capsule=Capsule(
        height=34,
        control=28,
        icon=16,
        spinner=14,
        dot=8,
        dots=18,
        wave_bars=18,
        part_gap=6,
        slot_gap=12,
        text_pad=12,
        icon_pad=10,
    ),
    menu=MenuGrid(width=320, radius=21, pad=6, head=34, track=10, gutter=8),
    detail=Detail(line=16, top=28, bottom=10),
)
