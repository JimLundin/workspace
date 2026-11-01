"""Routes desktop bridge commands to the feed, personal-work and canvas owners."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import assert_never

from assistant.feed_contracts import (
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
from assistant.work_bridge_contracts import BRIDGE_COMMAND, BRIDGE_RESPONSE, BridgeCommand, BridgeResponse, FeedResponse
from assistant.work_canvas_commands import CanvasCommand, CanvasResponse, ReadCanvas, UpdateCanvas
from automation import ipc
from automation.personal_work import (
    AddDocument,
    AddWebPage,
    DismissWork,
    ListSources,
    ListWork,
    PersonalRequest,
    PersonalResponse,
    ReadMeeting,
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
            case (
                AddDocument() | AddWebPage() | DismissWork() | RestoreWork() | ListWork() | ListSources() | ReadMeeting() | SaveWork() | UnlinkWork()
            ):
                return self.personal(command)
            case (
                ReadFeed()
                | ChooseSolution()
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


def answer(call: ipc.OwnerCall, desktop: WorkOwners, meeting: Callable[[ipc.MeetingOperation], ipc.OwnerResult]) -> ipc.OwnerResult:
    """Decode desktop text at its owner and encode the committed typed response."""
    match call:
        case ipc.DesktopCall(body):
            try:
                command = BRIDGE_COMMAND.validate_json(body)
                return ipc.Succeeded(BRIDGE_RESPONSE.dump_json(desktop.handle(command)).decode("utf-8"))
            except ValueError, TypeError:
                return ipc.Failed("The desktop owner rejected an invalid request.")
            except OSError:
                return ipc.Failed("The desktop owner is unavailable; inspect its current state before trying again.")
        case ipc.StartMeeting() | ipc.MeetingCommand():
            return meeting(call)
        case _:
            assert_never(call)
