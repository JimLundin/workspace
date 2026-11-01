"""Authenticated desktop bridge wire contracts, separate from feed decisions.

Canvas activity consumes feed decisions. This IO owner joins their responses
without making the feed domain depend on the canvas's activity model.
"""

from typing import Annotated, Final

from pydantic import Field, TypeAdapter

from assistant.feed_contracts import ChosenHandoff, FeedCommand, FeedRejected, FeedSnapshot, QueuedHandoff
from assistant.local_bridge import Contract, call
from assistant.work_canvas_commands import CanvasCommand, CanvasResponse
from automation.personal_work import PersonalRequest, PersonalResponse
from usage import DIRECTORY

type BridgeCommand = Annotated[FeedCommand | PersonalRequest | CanvasCommand, Field(discriminator="operation")]
type FeedResponse = FeedSnapshot | QueuedHandoff | ChosenHandoff | FeedRejected
type BridgeResponse = FeedResponse | PersonalResponse | CanvasResponse
BRIDGE_COMMAND = TypeAdapter(BridgeCommand)
BRIDGE_RESPONSE = TypeAdapter(BridgeResponse)
WORK_BRIDGE: Contract[BridgeCommand, BridgeResponse] = Contract("/feed", BRIDGE_COMMAND, BRIDGE_RESPONSE)
WORK_BRIDGE_ENDPOINT: Final = DIRECTORY / "work-feed-bridge.json"


def work_bridge_request(command: BridgeCommand) -> str:
    """Send a desktop command through the shared work bridge contract and endpoint."""
    return call(WORK_BRIDGE_ENDPOINT, WORK_BRIDGE, command)
