from fractions import Fraction
from pathlib import Path
from typing import Final

from contracts.members import every_member
from desktop_ui.application_observer import PlacementSpec
from desktop_ui.shell_items import PinnedApp, WebApp
from desktop_ui.window_layout import (
    Layout,
    Position,
    Program,
    Region,
    Role,
    Setup,
    Setups,
    Titled,
)
from winapi.shapes import Size

COMPANION: Final = Path(__file__).resolve().parents[2] / "companion"
"""Companion's checkout, beside Workspace's."""


OPEN_WEB_APP: Final = (
    "node",
    str(COMPANION / "src" / "process" / "main.ts"),
    "edge",
)
"""Companion opens the pinned web apps in the Edge it drives, on its own profile, starting it first when it isn't running."""


WEB_APPS: Final = every_member(
    PinnedApp,
    {
        PinnedApp.OUTLOOK: WebApp(
            "Outlook",
            "https://outlook.cloud.microsoft/mail/",
            "MSEdge.outlook.cloft_/mail/.EdgeProfile.Default",
            "mail",
        ),
        PinnedApp.TEAMS: WebApp(
            "Teams",
            "https://teams.cloud.microsoft/",
            "MSEdge.teams.clouicrosoft_/.EdgeProfile.Default",
            "chat",
        ),
    },
)


COMPANION_TABS: Final = frozenset({"MSEdge.EdgeProfile.Default"})
"""Companion's own tabs, in the tabbed window of its profile, which it keeps minimized and out of the owner's way."""


TERMINAL, EDGE = (Program("windowsterminal.exe"), Program("msedge.exe"))
"""Ordinary Edge is every Edge window that isn't a pinned web app's."""


SMD_TERMINAL, SMD_EDGE = (
    Titled(TERMINAL, "SMD comp"),
    Titled(EDGE, "sm-decomp"),
)
"""The SMD comp work on a desktop of its own: the terminal whose tab is once titled SMD comp, and the Edge window once showing the sm-decomp repository."""


FULL = Region(Fraction(0), Fraction(0), Fraction(1), Fraction(1))


LEFT_HALF = Region(Fraction(0), Fraction(0), Fraction(1, 2), Fraction(1))


RIGHT_HALF = Region(Fraction(1, 2), Fraction(0), Fraction(1, 2), Fraction(1))


SETUPS: Final = Setups(
    externals=frozendict(
        {
            Setup.LAPTOP_ONLY: frozendict(),
            Setup.HOME: frozendict({Size(3840, 2160): Role.MAIN}),
            Setup.WORK: frozendict(
                {Size(2560, 1440): Role.ABOVE, Size(1440, 2560): Role.SIDE}
            ),
        }
    ),
    layouts=frozendict(
        {
            Setup.LAPTOP_ONLY: Layout(
                frozendict(
                    {
                        TERMINAL: (Position(0, Role.LAPTOP, LEFT_HALF),),
                        PinnedApp.TEAMS: (
                            Position(0, Role.LAPTOP, RIGHT_HALF),
                        ),
                        EDGE: (Position(1, Role.LAPTOP, LEFT_HALF),),
                        PinnedApp.OUTLOOK: (
                            Position(1, Role.LAPTOP, RIGHT_HALF),
                        ),
                        SMD_TERMINAL: (Position(3, Role.LAPTOP, LEFT_HALF),),
                        SMD_EDGE: (Position(3, Role.LAPTOP, RIGHT_HALF),),
                    }
                ),
                others=Position(2, Role.LAPTOP, FULL),
            ),
            Setup.HOME: Layout(
                frozendict(
                    {
                        TERMINAL: (Position(0, Role.MAIN, FULL),),
                        PinnedApp.TEAMS: (Position(0, Role.LAPTOP, FULL),),
                        EDGE: (Position(1, Role.MAIN, FULL),),
                        PinnedApp.OUTLOOK: (Position(1, Role.LAPTOP, FULL),),
                        SMD_TERMINAL: (Position(3, Role.MAIN, FULL),),
                        SMD_EDGE: (Position(3, Role.LAPTOP, FULL),),
                    }
                ),
                others=Position(2, Role.MAIN, FULL),
            ),
            Setup.WORK: Layout(
                frozendict(
                    {
                        TERMINAL: (
                            Position(0, Role.ABOVE, FULL),
                            Position(0, Role.SIDE, FULL),
                        ),
                        PinnedApp.TEAMS: (Position(0, Role.LAPTOP, FULL),),
                        EDGE: (Position(1, Role.ABOVE, FULL),),
                        PinnedApp.OUTLOOK: (Position(1, Role.LAPTOP, FULL),),
                        SMD_TERMINAL: (Position(2, Role.ABOVE, FULL),),
                        SMD_EDGE: (Position(2, Role.SIDE, FULL),),
                    }
                ),
                others=Position(1, Role.SIDE, FULL),
            ),
        }
    ),
    dark_when_away=frozendict({Setup.HOME: frozenset({Role.MAIN})}),
)
"""Workspace's own setups; startup code passes them in, tests pass their own."""


PLACEMENT: Final = PlacementSpec(
    setups=SETUPS,
    web_apps=WEB_APPS,
    open_web_app=OPEN_WEB_APP,
    kept_away=COMPANION_TABS,
)
"""Placement as the desktop is handed it."""
