"""What the desktop is handed when it starts: the programs and places it shares with
the others, the apps the chords reach, and its own views' specs. Declares no values;
`desktop.__main__` builds them.
"""

from dataclasses import dataclass

from desktop_ui.application_observer import PlacementSpec
from desktop_ui.bar_events import BarSpec
from desktop_ui.components.appearance import Design
from desktop_ui.desktop_control import TrayMenuSpec
from desktop_ui.desktop_pager import PagerSpec
from desktop_ui.key_hint_overlay import BadgeSpec
from desktop_ui.keymap import KeyboardView
from desktop_ui.keymap_views import KeymapSpec
from desktop_ui.layer_indicator import IndicatorSpec
from desktop_ui.tray import TraySpec
from desktop_ui.window_switcher import SwitcherSpec
from protocol import App, Places, Programs


@dataclass(frozen=True, slots=True, kw_only=True)
class DesktopSettings:
    programs: Programs
    places: Places
    apps: tuple[App, ...]
    """The apps the chords reach, in chord-letter order."""
    keyboard: KeyboardView
    """The keyboard layout, as the key map, the key hints and the menu read it."""
    design: Design
    """How every window reads: its colours, glass, controls and type."""
    bar: BarSpec
    badges: BadgeSpec
    """The key-hint badges the bar shows over windows."""
    keymap: KeymapSpec
    indicator: IndicatorSpec
    switcher: SwitcherSpec
    tray: TraySpec
    tray_menu: TrayMenuSpec
    placement: PlacementSpec
    pager: PagerSpec
