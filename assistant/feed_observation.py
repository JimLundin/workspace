"""Feed observation: Teams work, Windows notices, console requests and triage joined into one snapshot.

Observers report each update as it arrives; the snapshot is what the agent view
renders. Commands from a card route back to the owner of their source.
"""

from dataclasses import dataclass, field, replace
from typing import assert_never

import assistant.communications
import assistant.notification_sources
from assistant.communications import Feed
from assistant.console_requests import Request
from assistant.feed_triage import Board
from assistant.notification_sources import HandleNotice, Notices, OpenApp, ReopenNotice, ToggleApp, joined


@dataclass(frozen=True, slots=True)
class FeedSnapshot:
    """The pending feed every view reads: Teams work and notices under one filter, console requests and triage."""

    communications: Feed = field(default_factory=Feed)
    console_requests: tuple[Request, ...] = ()
    triage: Board = field(default_factory=Board)


@dataclass(frozen=True, slots=True)
class FeedObservation:
    """The latest report from each observer, and the snapshot joined from them."""

    teams: Feed = field(default_factory=Feed)
    notices: Notices = field(default_factory=Notices)
    snapshot: FeedSnapshot = field(default_factory=FeedSnapshot)


@dataclass(frozen=True, slots=True)
class TeamsObserved:
    feed: Feed


@dataclass(frozen=True, slots=True)
class NoticesObserved:
    notices: Notices


@dataclass(frozen=True, slots=True)
class ConsolesObserved:
    requests: tuple[Request, ...]


@dataclass(frozen=True, slots=True)
class TriageObserved:
    board: Board


type FeedUpdate = TeamsObserved | NoticesObserved | ConsolesObserved | TriageObserved


@dataclass(frozen=True, slots=True)
class TriageInput:
    """The sources triage assesses."""

    communications: Feed
    requests: tuple[Request, ...]


@dataclass(frozen=True, slots=True)
class FeedChange:
    """The next observation; `assess` is present when the sources triage assesses were reported."""

    observation: FeedObservation
    assess: TriageInput | None


def observe(observation: FeedObservation, update: FeedUpdate) -> FeedChange:
    snapshot = observation.snapshot
    match update:
        case TeamsObserved(feed=teams):
            observation = replace(observation, teams=teams)
        case NoticesObserved(notices=notices):
            observation = replace(observation, notices=notices)
        case ConsolesObserved(requests=requests):
            observation = replace(observation, snapshot=replace(snapshot, console_requests=requests))
            return FeedChange(observation, TriageInput(snapshot.communications, requests))
        case TriageObserved(board=board):
            return FeedChange(replace(observation, snapshot=replace(snapshot, triage=board)), None)
        case _:
            assert_never(update)
    communications = joined(observation.teams, observation.notices)
    observation = replace(observation, snapshot=replace(snapshot, communications=communications))
    return FeedChange(observation, TriageInput(communications, snapshot.console_requests))


type SourceAction = assistant.communications.Command | assistant.notification_sources.Command


@dataclass(frozen=True, slots=True)
class ToNotices:
    """Qt's thread owns Windows notices, so handling one never waits behind a Teams navigation."""

    command: assistant.notification_sources.Command


@dataclass(frozen=True, slots=True)
class ToTeams:
    command: assistant.communications.Command


def route(command: SourceAction) -> ToNotices | ToTeams:
    match command:
        case HandleNotice() | ReopenNotice() | OpenApp() | ToggleApp():
            return ToNotices(command)
        case _:
            return ToTeams(command)
