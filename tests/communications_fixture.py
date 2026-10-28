"""Fictional communication observations, independent of any native UI."""

from assistant.communications import Conversation, Feed, Message, Status


def communication_feed() -> Feed:
    return Feed(status=Status.CONNECTED, detail="Teams · following two chats",
                conversations=(Conversation("19:one@thread.v2", "Anna"), Conversation("19:two@thread.v2", "Launch group")),
                followed=("19:one@thread.v2", "19:two@thread.v2"),
                messages=(Message("19:one@thread.v2", "one", "Anna", "Please review **these figures**.", 1, 2),))
