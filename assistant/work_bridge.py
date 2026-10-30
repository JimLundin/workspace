"""Routes desktop bridge commands to the feed, personal-work and canvas owners."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import assert_never

from assistant.feed_contracts import (
    AnswerConsole,
    ChooseSolution,
    ClearRules,
    CompleteItem,
    DismissItem,
    FeedCommand,
    FeedReply,
    ForgetRule,
    QuietItem,
    ReadFeed,
    RejectProposal,
    ReviseProposal,
    SaveRule,
)
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
            case (
                ReadFeed()
                | ChooseSolution()
                | AnswerConsole()
                | FeedReply()
                | SaveRule()
                | ForgetRule()
                | ClearRules()
                | CompleteItem()
                | QuietItem()
                | DismissItem()
                | RejectProposal()
                | ReviseProposal()
            ):
                return self.feed(command)
            case _ as unreachable:
                assert_never(unreachable)
