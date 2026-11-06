"""Desktop owner wire contracts, separate from feed decisions.

Canvas activity consumes feed decisions. This IO owner joins their responses
without making the feed domain depend on the canvas's activity model.
"""

from typing import Annotated

from pydantic import Field, TypeAdapter

from assistant.feed_contracts import ChosenHandoff, FeedCommand, FeedRejected, FeedSnapshot, QueuedHandoff
from contracts.personal_work import PersonalRequest, PersonalResponse
from contracts.work_canvas_commands import CanvasCommand, CanvasResponse

type BridgeCommand = Annotated[FeedCommand | PersonalRequest | CanvasCommand, Field(discriminator="operation")]
type FeedResponse = FeedSnapshot | QueuedHandoff | ChosenHandoff | FeedRejected
type BridgeResponse = FeedResponse | PersonalResponse | CanvasResponse
BRIDGE_COMMAND = TypeAdapter(BridgeCommand)
BRIDGE_RESPONSE = TypeAdapter(BridgeResponse)
