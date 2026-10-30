"""Feed observation: Teams work, Windows notices and console requests joined for triage.

Observers report each update as it arrives. Routine arrivals stay quiet: the
joined feed is what triage assesses, never a floating card.
"""

from dataclasses import dataclass, field, replace
from typing import assert_never

from assistant.communications import Feed
from assistant.console_requests import Request
from assistant.notification_sources import Notices, joined


@dataclass(frozen=True, slots=True)
class FeedObservation:
    """The latest report from each observer; `communications` joins Teams work and notices under one filter."""

    teams: Feed = field(default_factory=Feed)
    notices: Notices = field(default_factory=Notices)
    console_requests: tuple[Request, ...] = ()
    communications: Feed = field(default_factory=Feed)


@dataclass(frozen=True, slots=True)
class TeamsObserved:
    feed: Feed


@dataclass(frozen=True, slots=True)
class NoticesObserved:
    notices: Notices


@dataclass(frozen=True, slots=True)
class ConsolesObserved:
    requests: tuple[Request, ...]


type FeedUpdate = TeamsObserved | NoticesObserved | ConsolesObserved


def observe(observation: FeedObservation, update: FeedUpdate) -> FeedObservation:
    match update:
        case TeamsObserved(feed=teams):
            observation = replace(observation, teams=teams)
        case NoticesObserved(notices=notices):
            observation = replace(observation, notices=notices)
        case ConsolesObserved(requests=requests):
            return replace(observation, console_requests=requests)
        case _:
            assert_never(update)
    return replace(observation, communications=joined(observation.teams, observation.notices))
