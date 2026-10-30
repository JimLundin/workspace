"""Routes desktop bridge commands to the feed, personal-work and canvas owners."""

from collections.abc import Callable
from dataclasses import dataclass

from assistant.feed_contracts import FeedCommand
from assistant.work_bridge_contracts import BridgeCommand, BridgeResponse, FeedResponse
from assistant.work_canvas_commands import CanvasCommand, CanvasResponse, ReadCanvas, UpdateCanvas
from automation.personal_work import (
    AddDocument,
    AddWebPage,
    DismissWork,
    ListSources,
    ListWork,
    PersonalRequest,
    PersonalResponse,
    RestoreWork,
    SaveWork,
    UnlinkWork,
)


@dataclass(frozen=True, slots=True)
class WorkOwners:
    """Each owner's typed handler for its part of the bridge contract."""

    feed: Callable[[FeedCommand], FeedResponse]
    personal: Callable[[PersonalRequest], PersonalResponse]
    canvas: Callable[[CanvasCommand], CanvasResponse]

    def handle(self, command: BridgeCommand) -> BridgeResponse:
        match command:
            case ReadCanvas() | UpdateCanvas():
                return self.canvas(command)
            case AddDocument() | AddWebPage() | DismissWork() | RestoreWork() | ListWork() | ListSources() | SaveWork() | UnlinkWork():
                return self.personal(command)
            case _:
                return self.feed(command)
