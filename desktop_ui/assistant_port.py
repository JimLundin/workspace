"""What the desktop asks of the assistant.

The desktop never touches the assistant's owners: it sends `contracts.desktop_link`
commands through an `AssistantPort`, and runs on without them while the assistant
is down. `LinkedAssistant` carries them over the link to the assistant process.
"""

from dataclasses import dataclass
from typing import Protocol

from contracts.desktop_link import ToAssistant, to_assistant
from link.client import Client


class AssistantPort(Protocol):
    def send(self, command: ToAssistant) -> bool:
        """Queue a command; False while the assistant is down."""
        ...


@dataclass(frozen=True, slots=True)
class LinkedAssistant:
    """The assistant process, over the link's client end."""

    client: Client

    def send(self, command: ToAssistant) -> bool:
        return self.client.send(to_assistant(command))
