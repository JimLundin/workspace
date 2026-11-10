"""What the desktop is handed when it starts: the programs and places it shares with
the others, the apps the chords reach, and its own views' specs. Declares no values;
`desktop.__main__` builds them.
"""

from dataclasses import dataclass

from desktop_ui.bar_events import BarSpec
from desktop_ui.components.appearance import Design
from protocol import App, Places, Programs


@dataclass(frozen=True, slots=True, kw_only=True)
class DesktopSettings:
    programs: Programs
    places: Places
    apps: tuple[App, ...]
    """The apps the chords reach, in chord-letter order."""
    design: Design
    """How every window reads: its colours, glass, controls and type."""
    bar: BarSpec
