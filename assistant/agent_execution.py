"""The agent execution adapter owns durable runs' SDK history, workspaces, and cleanup."""

import contextlib
import hashlib
import sqlite3
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from assistant.activity import ContextSnapshot
from assistant.agent import Agent, Log
from assistant.agent_history import History
from assistant.agent_tools import Machine
from assistant.llm import Settings
from assistant.meeting_execution import MeetingWork
from assistant.self_change_tools import verified_installation
from assistant.workspace import Workspace
from automation.actions import ActionError, Resources
from automation.execution import ApprovalReview, Incomplete, Outcome, WorkExecution
from automation.store import TaskStore
from automation.task import Blocked, Claim, RequestSource, Waiting
from diagnostics import failure_info
from usage import Detail


@dataclass(frozen=True, slots=True)
class Conversation:
    history: History
    workspace: Workspace


class AgentExecution:
    __slots__ = (
        "close_background",
        "context",
        "conversations",
        "machine",
        "meeting",
        "record",
        "report_error",
        "resources",
        "settings",
        "workspace",
    )

    def __init__(
        self,
        settings: Settings,
        machine: Machine,
        *,
        record: Callable[[Mapping[str, Detail]], None],
        report_error: Callable[[str], None],
        close_background: Callable[[], None],
        context: Callable[[], ContextSnapshot] | None = None,
        workspace: Workspace | None = None,
        resources: Resources | None = None,
        meeting: MeetingWork | None = None,
    ) -> None:
        self.settings, self.machine, self.context = settings, machine, context
        self.record, self.report_error, self.close_background = record, report_error, close_background
        self.workspace = workspace if workspace is not None else Workspace()
        self.resources = resources if resources is not None else Resources()
        self.meeting = meeting
        self.conversations: OrderedDict[str, Conversation] = OrderedDict()

    def conversation(self, claim: Claim) -> Conversation:
        source = claim.task.source
        name = "conversation:" + source.conversation_id if isinstance(source, RequestSource) else "task:" + claim.task.id
        return self._conversation(name)

    def _conversation(self, name: str) -> Conversation:
        key = hashlib.sha256(name.encode("utf-8")).hexdigest()
        if key not in self.conversations:
            draft = self.workspace.root.parent / "workspaces" / key
            self.conversations[key] = Conversation(History(), Workspace(self.workspace.live, draft, resume=True))
        self.conversations.move_to_end(key)
        while len(self.conversations) > 8:
            self.conversations.popitem(last=False)
        return self.conversations[key]

    def run_work(
        self,
        claim: Claim,
        store: TaskStore,
        log: Log,
        stop: threading.Event,
        *,
        context: ContextSnapshot | None = None,
        context_text: str = "",
        review: Callable[[ApprovalReview], bool] | None = None,
    ) -> Outcome:
        """Execute one durable claim; the controller commits the returned disposition."""
        started = time.monotonic()
        try:
            if self.meeting is None and claim.task.id.startswith("meeting-followup-"):
                raise ValueError("Meeting follow-up is not configured for this work process.")
            followup = self.meeting.session(claim.task) if self.meeting is not None else None
        except (OSError, ValueError, sqlite3.Error) as error:
            reason = f"Meeting preparation could not be opened: {error}"[:4000]
            log.problem(reason)
            return Waiting(Blocked(reason))
        selected = followup is not None
        work = WorkExecution(claim, store, self.resources, context_text="" if selected else context_text, review=review)
        session = self._conversation("task:" + claim.task.id) if selected else self.conversation(claim)
        agent = Agent(
            self.settings,
            self.machine,
            log,
            stop,
            work=work,
            workspace=session.workspace,
            history=session.history,
            context=None if selected else context,
            context_reader=None if selected else self.context,
            install_root=self.workspace.root,
            followup=followup,
        )
        try:
            if stop.is_set():
                return Waiting(Blocked("Execution stopped before it started."))
            work.actions.reconcile(stop)
            if followup is not None:
                followup.recover(work, stop)
            if (installation := verified_installation(store, claim, session.workspace.live)) is not None:
                return installation
            agent.run(claim.task.prompt)
            outcome = work.outcome(agent.report, stop)
            return followup.completed(outcome) if followup is not None else outcome
        except (ActionError, OSError, ValueError) as error:
            fault = failure_info(error)
            self.report_error(f"Agent execution failed: {fault.kind}; {' > '.join(fault.locations)}")
            reason = "Execution could not establish a durable result. Resume to inspect its state."
            log.problem(reason)
            agent.report = Incomplete(str(error))
            return Waiting(Blocked(reason))
        except Exception as error:
            fault = failure_info(error)
            self.report_error(f"Agent execution failed: {fault.kind}; {' > '.join(fault.locations)}")
            log.problem("Something went wrong; it's in the assistant's log.")
            return Waiting(Blocked("Execution failed before a verified result. Resume to inspect its state."))
        finally:
            if stop.is_set():
                self.close_background()
            with contextlib.suppress(OSError):
                self.record({"durable": True, "seconds": round(time.monotonic() - started, 1), **agent.timings})
