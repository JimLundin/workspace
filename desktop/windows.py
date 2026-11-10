"""The desktop's other windows: the key map and its overlay, the layer indicator,
the window switcher, the key-hint badges and the tray icon and its menu. Only
declarations; `desktop.__main__` hands them to the desktop.
"""

from typing import Final

from contracts.members import every_member
from contracts.status import State
from desktop import bar, look
from desktop_ui.colour import Rgb
from desktop_ui.components.appearance import Scheme
from desktop_ui.desktop_control import Menu, Separator, TrayAction, TrayMenuSpec, TrayWords
from desktop_ui.key_hint_overlay import BadgeSpec
from desktop_ui.keymap import KeymapWords, Role
from desktop_ui.keymap_views import Bindings, KeymapSpec, KeysSpec, Lit, MapWindowSpec, OverlaySpec
from desktop_ui.layer_indicator import IndicatorSpec
from desktop_ui.navigation import Direction
from desktop_ui.tray import TraySpec
from desktop_ui.window_switcher import SwitcherSpec
from keyboard.actions import Chord
from keyboard.keys import Key
from protocol import Tool

BADGES: Final = BadgeSpec(
    height=26,
    cap=20,
    gap=4,
    pad=6,
    corner=8,
    font=look.TYPE.label,
    arrows=every_member(Direction, {Direction.LEFT: "←", Direction.DOWN: "↓", Direction.UP: "↑", Direction.RIGHT: "→"}),
    scheme=Scheme.DARK,
    glass=look.GLASS,
    palette=look.PALETTE,
)
"""Workspace's badges; the bar passes them to the overlay."""


KEYMAP_WORDS: Final = KeymapWords(
    tools=frozendict(
        {
            Tool.DICTATE: "Talk",
            Tool.ZOOM: "Zoom",
            Tool.FOCUS_LEFT: "Focus ←",
            Tool.FOCUS_DOWN: "Focus ↓",
            Tool.FOCUS_UP: "Focus ↑",
            Tool.FOCUS_RIGHT: "Focus →",
            Tool.DESKTOP_1: "Desk 1",
            Tool.DESKTOP_2: "Desk 2",
            Tool.DESKTOP_3: "Desk 3",
            Tool.DESKTOP_4: "Desk 4",
            Tool.DESKTOP_5: "Desk 5",
            Tool.PLACEMENT_PAUSE: "Pause place",
            Tool.PLACE_NOW: "Re-place",
            Tool.MEETING_TOGGLE: "Record",
            Tool.COPY_TRANSCRIPT: "Copy speech",
            Tool.DICTATE_TOGGLE: "Dictate toggle",
            Tool.WINDOW_SWITCHER: "Windows",
        }
    ),
    chords=frozendict(
        {Chord.ctrl(Key.Z): "Undo", Chord.ctrl(Key.Y): "Redo", Chord.ctrl(Key.C): "Copy", Chord.ctrl(Key.V): "Paste", Chord.ctrl(Key.X): "Cut"}
    ),
    chord_hold="Apps",
    hold="hold",
    escape="On/off",
    escape_hold="hold: quit",
    held="held",
)
"""The key map's words."""


KEYMAP: Final = KeymapSpec(
    keys=KeysSpec(
        unit=64,
        gap=5,
        height=56,
        rows=(0.0, 1.5, 0.0, 1.25, 3.5),
        columns=14,
        widths=frozendict({"Space": 6.25, "Caps": 1.75}),
        corner=9,
        corner_least=4,
        name=look.TYPE.keycap_name,
        name_least=8,
        name_inset=3,
        hold_bottom=3,
        legend=look.TYPE.keycap,
        legend_long=look.TYPE.keycap_long,
        legend_short=5,
        legend_least=7,
        legend_fit=6,
        held=Lit(look.PALETTE.accent, look.PALETTE.on_accent),
        bindings=every_member(
            Scheme,
            {
                Scheme.DARK: Bindings(
                    0.16, frozendict({Role.MOD: "#64d2ff", Role.LAYER: "#7ab0f2", Role.TOOL: "#ffb340", Role.APP: "#30d158", Role.SPECIAL: "#da8fff"})
                ),
                Scheme.LIGHT: Bindings(
                    0.12, frozendict({Role.MOD: "#0071a4", Role.LAYER: "#2f6fc4", Role.TOOL: "#b25000", Role.APP: "#248a3d", Role.SPECIAL: "#8944ab"})
                ),
            },
        ),
        pressed=every_member(Scheme, {Scheme.DARK: Lit("#f5f5f7", "#161618"), Scheme.LIGHT: Lit("#1d1d1f", "#ffffff")}),
    ),
    overlay=OverlaySpec(
        opacity=0.55,
        radius=20,
        side=12,
        top=10,
        bottom=12,
        spacing=8,
        heading_inset=4,
        heading="Workspace keyboard",
        smallest=0.2,
        largest=0.85,
        margin=32,
        reserve=180,
        rest=90,
        handle_radius=14,
        handle_leading=12,
        handle_trailing=14,
        handle_padding=6,
        handle_spacing=6,
        handle_glyph="menu",
        handle_text="Drag to move",
        handle_name="Drag to move the keyboard overlay",
        handle_gap=4,
        tap=0.12,
    ),
    window=MapWindowSpec(
        title="Workspace key map", width=940, height=390, side=20, top=16, hint="Hold . for Apps: L dictate · ' dictation toggle · S windows"
    ),
)
"""Workspace's key map and overlay; the desktop app opens them with it."""


INDICATOR: Final = IndicatorSpec(
    radius=bar.SIZES.bar.radius,  # The island's capsule, so the two read as one family.
    padding=16,
    leading=8,
    opacity=0.9,
    font=look.TYPE.title,
    bottom=28,
    flash=1.2,
    flash_ink=look.PALETTE.accent,
    layout_on="Layout on",
    layout_off="Layout off",
)


SWITCHER: Final = SwitcherSpec(
    width=640,
    tallest=560,
    chrome=104,
    fewest=1,
    most=7,
    radius=26,
    inset=12,
    row=52,
    text_side=14,
    text_top=7,
    selected_detail=0.75,
    field_side=10,
    field_top=16,
    field_bottom=14,
    field_spacing=10,
    symbol="search",
    symbol_size=20,
    placeholder="Find a window…",
    field_name="Find an open window",
    list_name="Open windows",
    separator=1,
    separator_gap=8,
    bottom=10,
    hint="↑ ↓ select · Enter switch · Escape close",
    hint_side=10,
    hint_top=8,
    minimized=" · minimized",
    shadow=24,
    shadow_lift=8,
    shadow_drop=10,
    shadow_step=2,
    shadow_alpha=6,
)
"""Workspace's switcher; the desktop app opens it with this."""


TRAY_ICON: Final = TraySpec(
    name="Workspace",
    size=32,
    colours=frozendict(
        {
            State.READY: Rgb(46, 160, 120),
            State.LAYOUT_OFF: Rgb(140, 140, 140),
            State.LISTENING: Rgb(220, 50, 50),
            State.RECORDING: Rgb(230, 64, 85),
            State.WORKING: Rgb(235, 160, 30),
        }
    ),
)


TRAY_MENU: Final = TrayMenuSpec(
    items=(
        TrayAction(Menu.TOGGLE_LAYOUT),
        TrayAction(Menu.RESTART_LAYOUT),
        TrayAction(Menu.OVERLAY, "Keyboard overlay"),
        TrayAction(Menu.KEYMAP, "Key map"),
        Separator(),
        TrayAction(Menu.MEETING),
        TrayAction(Menu.TRANSCRIPTS, "Open meeting transcripts"),
        Separator(),
        TrayAction(Menu.LOGS, "Open logs folder"),
        Separator(),
        TrayAction(Menu.RESTART_DESKTOP, "Restart desktop"),
        TrayAction(Menu.QUIT, "Quit Workspace"),
    ),
    words=TrayWords(
        layout="Layout",
        on="on",
        off="off",
        not_running="not running",
        toggle_key="Tap §",
        restart="Restart layout",
        start="Start layout",
        record="Record a meeting",
        stop_recording="Stop recording",
    ),
)
"""The tray icon's menu. The layout and meeting items word their own state."""
