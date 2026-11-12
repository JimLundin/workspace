"""Where windows go on each setup of screens, and the web apps pinned beside them.
Only declarations; `desktop.__main__` hands them to the desktop.
"""

from fractions import Fraction
from pathlib import Path
from typing import Final

from contracts.members import every_member
from desktop_ui.application_observer import PlacementSpec
from desktop_ui.shell_items import PinnedApp, WebApp
from desktop_ui.window_layout import Layout, Position, Program, Region, Role, Setup, Setups
from winapi.shapes import Size

COMPANION: Final = Path(__file__).resolve().parents[2] / "elwing"
"""Companion's checkout, beside Workspace's."""


OPEN_WEB_APP: Final = ("node", str(COMPANION / "src" / "process" / "main.ts"), "edge")
"""Companion opens the pinned web apps in the Edge it drives, on its own profile, starting it first when it isn't running."""


# Edge shortens each part of an app window's id to 20 characters by cutting out its middle.
WEB_APPS: Final = every_member(
    PinnedApp,
    {
        PinnedApp.OUTLOOK: WebApp("Outlook", "https://outlook.cloud.microsoft/mail/", "MSEdge.outlook.cloft_/mail/.EdgeProfile.Default", "mail"),
        PinnedApp.TEAMS: WebApp("Teams", "https://teams.cloud.microsoft/", "MSEdge.teams.clouicrosoft_/.EdgeProfile.Default", "chat"),
    },
)


COMPANION_TABS: Final = frozenset({"MSEdge.EdgeProfile.Default"})
"""Companion's own tabs, in the tabbed window of its profile, which it keeps minimized and out of the owner's way."""


TERMINAL, CODE, EDGE = Program("windowsterminal.exe"), Program("code.exe"), Program("msedge.exe")
"""Ordinary Edge is every Edge window that isn't a pinned web app's."""


FULL = Region(Fraction(0), Fraction(0), Fraction(1), Fraction(1))


LEFT_HALF = Region(Fraction(0), Fraction(0), Fraction(1, 2), Fraction(1))


RIGHT_HALF = Region(Fraction(1, 2), Fraction(0), Fraction(1, 2), Fraction(1))


SETUPS: Final = Setups(
    externals=frozendict(
        {
            Setup.LAPTOP_ONLY: frozendict(),
            Setup.HOME: frozendict({Size(3840, 2160): Role.MAIN}),
            # Orientation, not arrangement, tells the two work screens apart.
            Setup.WORK: frozendict({Size(2560, 1440): Role.ABOVE, Size(1440, 2560): Role.SIDE}),
        }
    ),
    layouts=frozendict(
        {
            # Desktops count from 0, the first in Task View; a setup keeps exactly the desktops it names.
            Setup.LAPTOP_ONLY: Layout(
                frozendict(
                    {
                        PinnedApp.OUTLOOK: (Position(0, Role.LAPTOP, LEFT_HALF),),
                        PinnedApp.TEAMS: (Position(0, Role.LAPTOP, RIGHT_HALF),),
                        # Terminals side by side; Code's windows share all of their desktop, so a lone one fills it.
                        TERMINAL: (Position(1, Role.LAPTOP, LEFT_HALF), Position(1, Role.LAPTOP, RIGHT_HALF)),
                        CODE: (Position(2, Role.LAPTOP, FULL),),
                        EDGE: (Position(3, Role.LAPTOP, FULL),),
                    }
                ),
                others=Position(4, Role.LAPTOP, FULL),
            ),
            Setup.HOME: Layout(
                frozendict(
                    {
                        # Terminals and Code share the 4K screen equally, terminals first, Edge on the laptop below.
                        TERMINAL: (Position(0, Role.MAIN, FULL),),
                        CODE: (Position(0, Role.MAIN, FULL),),
                        EDGE: (Position(0, Role.LAPTOP, FULL),),
                        PinnedApp.OUTLOOK: (Position(1, Role.MAIN, LEFT_HALF),),
                        PinnedApp.TEAMS: (Position(1, Role.MAIN, RIGHT_HALF),),
                    }
                ),
                others=Position(1, Role.LAPTOP, FULL),
            ),
            Setup.WORK: Layout(
                frozendict(
                    {
                        # Code takes the tall screen, the terminals the one above, Edge the laptop.
                        CODE: (Position(0, Role.SIDE, FULL),),
                        TERMINAL: (Position(0, Role.ABOVE, FULL),),
                        EDGE: (Position(0, Role.LAPTOP, FULL),),
                        PinnedApp.OUTLOOK: (Position(1, Role.ABOVE, LEFT_HALF),),
                        PinnedApp.TEAMS: (Position(1, Role.ABOVE, RIGHT_HALF),),
                    }
                ),
                others=Position(1, Role.LAPTOP, FULL),
            ),
        }
    ),
    # The home 4K screen is an OLED.
    dark_when_away=frozendict({Setup.HOME: frozenset({Role.MAIN})}),
)
"""Workspace's own setups; startup code passes them in, tests pass their own."""


PLACEMENT: Final = PlacementSpec(setups=SETUPS, web_apps=WEB_APPS, open_web_app=OPEN_WEB_APP, kept_away=COMPANION_TABS)
"""Placement as the desktop is handed it."""
