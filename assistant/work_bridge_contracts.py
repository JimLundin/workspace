"""Authenticated desktop bridge wire contracts, separate from feed decisions.

Canvas activity consumes feed decisions. This IO owner joins their responses
without making the feed domain depend on the canvas's activity model.
"""

from collections.abc import Mapping

from pydantic import TypeAdapter

from assistant.feed_contracts import ChosenHandoff, ConsoleAnswered, FeedRejected, FeedReply, FeedSnapshot, QueuedHandoff
from assistant.work_canvas_commands import CanvasCommand, CanvasResponse
from automation.personal_work import PersonalRequest, PersonalResponse

type BridgeCommand = Mapping[str, object] | FeedReply | PersonalRequest | CanvasCommand
type BridgeResponse = FeedSnapshot | QueuedHandoff | ChosenHandoff | ConsoleAnswered | FeedRejected | PersonalResponse | CanvasResponse
BRIDGE_RESPONSE = TypeAdapter(BridgeResponse)
