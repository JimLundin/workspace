"""Source identity for compact feed badges, independent of notification text."""

from dataclasses import dataclass
from enum import Enum


class App(Enum):
    WORKSPACE = 'Workspace'
    TEAMS = 'Microsoft Teams'
    OUTLOOK = 'Outlook'
    CODEX = 'Codex'
    CLAUDE = 'Claude Code'
    EDGE = 'Microsoft Edge'
    WINDOWS = 'Windows'


@dataclass(frozen=True, slots=True)
class Origin:
    app: App
    name: str


def application(name: str, app_id: str = '') -> Origin:
    identity = (name + ' ' + app_id).casefold()
    for app, aliases in ((App.TEAMS, ('teams',)), (App.OUTLOOK, ('outlook', 'mail', 'e-post')),
                         (App.CODEX, ('codex',)), (App.CLAUDE, ('claude',)),
                         (App.WORKSPACE, ('workspace',)), (App.EDGE, ('microsoftedge', 'microsoft edge'))):
        if any(alias in identity for alias in aliases):
            return Origin(app, app.value)
    return Origin(App.WINDOWS, name or App.WINDOWS.value)


@dataclass(frozen=True, slots=True)
class FeedRequest:
    identity: str
    title: str
