"""What the desktop asks of the assistant, which runs on its own thread in this process.

The desktop never touches the assistant's owners: it sends `contracts.desktop_link`
commands through an `AssistantPort`, and the assistant publishes back through the
function the desktop gives it. `desktop` composes the two.
"""

from collections.abc import Callable
from typing import Protocol

from contracts.desktop_link import ToAssistant, ToDesktop


class AssistantPort(Protocol):
    def send(self, command: ToAssistant) -> None:
        """Queue a command for the assistant's control thread."""
        ...

    def close(self) -> None: ...


type StartAssistant = Callable[[Callable[[ToDesktop], None]], AssistantPort]
"""Start the assistant with the function it publishes to the desktop through."""
