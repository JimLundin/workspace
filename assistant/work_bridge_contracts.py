"""Authenticated desktop bridge wire contracts, separate from feed decisions.

Canvas activity consumes feed decisions. This IO owner joins their responses
without making the feed domain depend on the canvas's activity model.
"""

from typing import Annotated

from pydantic import Field, TypeAdapter

from assistant.feed_contracts import ChosenHandoff, ConsoleAnswered, FeedCommand, FeedRejected, FeedSnapshot, QueuedHandoff
from assistant.work_canvas_commands import CanvasCommand, CanvasResponse
from automation.personal_work import PersonalRequest, PersonalResponse

type BridgeCommand = Annotated[FeedCommand | PersonalRequest | CanvasCommand, Field(discriminator="operation")]
type BridgeResponse = FeedSnapshot | QueuedHandoff | ChosenHandoff | ConsoleAnswered | FeedRejected | PersonalResponse | CanvasResponse
BRIDGE_COMMAND = TypeAdapter(BridgeCommand)
BRIDGE_RESPONSE = TypeAdapter(BridgeResponse)
