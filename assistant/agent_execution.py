"""The agent execution adapter owns durable runs' SDK history, workspaces, and cleanup."""

import contextlib
import hashlib
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Mapping
from typing import assert_never

from assistant.agent import Agent
from assistant.agent_history import History
from assistant.agent_tools import Machine
from assistant.llm import Settings
from assistant.meeting_execution import MeetingWork
from assistant.task_profiles import UNSEEN, Conversation, GeneralRun, MeetingFollowupRun, ProfileRun, RequestContext
from assistant.workspace import Workspace
from automation.actions import ActionError, Resources
from automation.execution import ApprovalReview, Incomplete, Log, WorkExecution
from automation.store import TaskStore
from automation.task import Blocked, Claim, FeedHandoff, MeetingFollowup, Outcome, RequestKind, RequestSource, Task, Waiting, task_profile
from diagnostics import failure_info
from usage import Detail


def unseen(_task: Task) -> RequestContext:
    return UNSEEN


class ProfileError(Exception):
    """The task's profile cannot run: the reason is shown and the task waits."""


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
        context: Callable[[Task], RequestContext] = unseen,
        workspace: Workspace | None = None,
        resources: Resources | None = None,
        meeting: MeetingWork | None = None,
    ) -> None:
        # `context` is read only for a profile that admits the request's desktop context.
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

    def profile(self, claim: Claim) -> ProfileRun:
        """The one place a task's profile selects its run."""
        match profile := task_profile(claim.task.source):
            case MeetingFollowup():
                # A missing or changed preparation must not silently gain the general profile.
                if self.meeting is None:
                    raise ProfileError("Meeting follow-up is not configured for this work process.")
                try:
                    run = self.meeting.session(claim.task.id, profile)
                except (OSError, ValueError) as error:
                    raise ProfileError(f"Meeting preparation could not be opened: {error}"[:4000]) from error
                return MeetingFollowupRun(self._conversation("task:" + claim.task.id), run)
            case RequestKind.GENERAL | FeedHandoff():
                return GeneralRun(self.conversation(claim), self.context(claim.task), self.workspace.root)
            case _:
                assert_never(profile)

    def run_work(
        self,
        claim: Claim,
        store: TaskStore,
        log: Log,
        stop: threading.Event,
        *,
        review: Callable[[ApprovalReview], bool] | None = None,
    ) -> Outcome:
        """Execute one durable claim; the controller commits the returned disposition.

        The four positional inputs are the controller's `WorkExecution.run_work`
        contract; `review` is the work process's per-claim approval channel.
        """
        started = time.monotonic()
        try:
            profile = self.profile(claim)
        except ProfileError as error:
            log.problem(str(error))
            return Waiting(Blocked(str(error)))
        work = WorkExecution(claim, store, self.resources, context_text=profile.context.saved, review=review)
        agent = Agent(
            self.settings,
            self.machine,
            log,
            stop,
            work=work,
            toolset=profile.toolset,
            history=profile.conversation.history,
            context=profile.context.invocation,
            context_reader=profile.context.current,
        )
        try:
            if stop.is_set():
                return Waiting(Blocked("Execution stopped before it started."))
            work.actions.reconcile(stop)
            if (recovered := profile.recover(work, stop)) is not None:
                return recovered
            agent.run(claim.task.prompt)
            return profile.completed(work.outcome(agent.report, stop))
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
