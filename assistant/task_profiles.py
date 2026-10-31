"""Each task profile's execution: what its run continues, sees, offers, recovers and checks.

Execution selects one profile run from the task's profile and runs whatever it
supplies without branching on the profile.
"""

import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Protocol

from assistant.agent import Agent, Toolset
from assistant.agent_history import History
from assistant.agent_toolsets import General, MeetingFollowupTools
from assistant.meeting_execution import MeetingRun
from assistant.self_change_tools import verified_installation
from assistant.workspace import Workspace
from automation.activity import ContextSnapshot
from automation.execution import WorkExecution
from automation.task import Outcome, Waiting


@dataclass(frozen=True, slots=True)
class Conversation:
    """The SDK history and source draft a run continues."""

    history: History
    workspace: Workspace


@dataclass(frozen=True, slots=True)
class RequestContext:
    """The desktop context a request was made in: its invocation, saved project context and the live desktop."""

    invocation: ContextSnapshot | None
    saved: str
    current: Callable[[], ContextSnapshot] | None


UNSEEN: Final = RequestContext(None, "", None)
"""No desktop context: the agent sees only its task's own sources."""


class ProfileRun(Protocol):
    """One claim's execution under its task profile."""

    @property
    def conversation(self) -> Conversation: ...
    @property
    def context(self) -> RequestContext:
        """The desktop context this profile admits."""
        ...

    def toolset(self, agent: Agent) -> Toolset: ...
    def recover(self, work: WorkExecution, stop: threading.Event) -> Waiting | None:
        """Settle what earlier runs left uncertain before the agent starts; a disposition ends this run."""
        ...

    def completed(self, outcome: Outcome) -> Outcome:
        """The profile's completion check over the work's outcome."""
        ...


class GeneralRun:
    """A general request continues its conversation with the request's desktop context, the whole desktop and self-change."""

    __slots__ = ("context", "conversation", "install_root")

    def __init__(self, conversation: Conversation, context: RequestContext, install_root: Path) -> None:
        self.conversation, self.context, self.install_root = conversation, context, install_root

    def toolset(self, agent: Agent) -> Toolset:
        return General(agent, workspace=self.conversation.workspace, install_root=self.install_root)

    def recover(self, work: WorkExecution, stop: threading.Event) -> Waiting | None:
        """A requested installation finishes when the running source matches its checked digest."""
        return verified_installation(work.store, work.claim, self.conversation.workspace.live)

    def completed(self, outcome: Outcome) -> Outcome:
        return outcome


class MeetingFollowupRun:
    """A prepared meeting follow-up sees only its selected recordings in a conversation of its own."""

    __slots__ = ("conversation", "run")

    def __init__(self, conversation: Conversation, run: MeetingRun) -> None:
        # The assistant captures no desktop context for these submissions either (`WorkAgent.submit_identified`).
        self.conversation, self.run = conversation, run

    @property
    def context(self) -> RequestContext:
        return UNSEEN

    def toolset(self, agent: Agent) -> Toolset:
        return MeetingFollowupTools(agent, self.run)

    def recover(self, work: WorkExecution, stop: threading.Event) -> Waiting | None:
        """An uncertain draft save is resolved by its exact readback, or the run fails without a verified result."""
        self.run.recover(work, stop)
        return None

    def completed(self, outcome: Outcome) -> Outcome:
        """Complete only after the package is published and each draft's save is verified."""
        return self.run.completed(outcome)
