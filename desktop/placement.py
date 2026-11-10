"""Where windows go on each setup of screens, and the web apps pinned beside them.
Only declarations; `desktop.__main__` hands them to the desktop.
"""

from fractions import Fraction
from typing import Final

from contracts.members import every_member
from desktop_ui.application_observer import PlacementSpec
from desktop_ui.shell_items import PinnedApp, WebApp
from desktop_ui.window_layout import Layout, Position, Program, Region, Role, Setup, Setups
from winapi.shapes import Size

WEB_APPS: Final = every_member(
    PinnedApp,
    {
        PinnedApp.OUTLOOK: WebApp("Outlook", "https://outlook.cloud.microsoft/mail/", "MSEdge.outlook.cloud.microsoft_/mail/", "mail"),
        PinnedApp.TEAMS: WebApp("Teams", "https://teams.cloud.microsoft/", "MSEdge.teams.cloud.microsoft_/", "chat"),
    },
)


TERMINAL, CODE, EDGE = Program("windowsterminal.exe"), Program("code.exe"), Program("msedge.exe")
"""Ordinary Edge is every Edge window that isn't a pinned web app's."""


FULL = Region(Fraction(0), Fraction(0), Fraction(1), Fraction(1))


LEFT_HALF = Region(Fraction(0), Fraction(0), Fraction(1, 2), Fraction(1))


RIGHT_HALF = Region(Fraction(1, 2), Fraction(0), Fraction(1, 2), Fraction(1))


LEFT_TWO_THIRDS = Region(Fraction(0), Fraction(0), Fraction(2, 3), Fraction(1))


RIGHT_THIRD = Region(Fraction(2, 3), Fraction(0), Fraction(1, 3), Fraction(1))


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
                        # Two terminals read Terminal | Terminal | Code across the 4K screen, Edge on the laptop below.
                        TERMINAL: (Position(0, Role.MAIN, LEFT_TWO_THIRDS),),
                        CODE: (Position(0, Role.MAIN, RIGHT_THIRD),),
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


PLACEMENT: Final = PlacementSpec(setups=SETUPS, web_apps=WEB_APPS)
"""Placement as the desktop is handed it."""
