"""The agent execution adapter runs a selected profile and owns metrics, errors and cleanup."""

import contextlib
import threading
import time
from collections.abc import Callable, Mapping
from typing import Protocol

from assistant.agent import Agent
from assistant.agent_tools import Machine
from assistant.llm import Settings
from assistant.task_profiles import Profiles
from automation.actions import ActionError, Resources
from automation.execution import Incomplete, Log, WorkExecution
from automation.store import TaskStore
from automation.task import Blocked, Claim, Outcome, Waiting
from diagnostics import failure_info
from usage import Detail


class BackgroundCleanup(Protocol):
    """Run-end cleanup releases pages; cancellation also releases the browser."""

    def __call__(self, *, keep_browser: bool) -> None: ...


class AgentExecution:
    __slots__ = (
        "close_background",
        "machine",
        "profiles",
        "record",
        "report_error",
        "resources",
        "settings",
    )

    def __init__(  # noqa: PLR0913 - injected collaborators and callbacks
        self,
        settings: Settings,
        machine: Machine,
        profiles: Profiles,
        *,
        record: Callable[[Mapping[str, Detail]], None],
        report_error: Callable[[str], None],
        close_background: BackgroundCleanup,
    ) -> None:
        # Settings, machine and profiles supply the run; recording, error reporting,
        # cancellation cleanup and resource ownership are independent run effects.
        self.settings, self.machine, self.profiles = settings, machine, profiles
        self.record, self.report_error, self.close_background = record, report_error, close_background
        self.resources = Resources()

    def run_work(self, claim: Claim, store: TaskStore, log: Log, stop: threading.Event) -> Outcome:
        """Execute one durable claim; the controller commits the returned disposition."""
        started = time.monotonic()
        profile = self.profiles.run(claim)
        work = WorkExecution(claim, store, self.resources, context_text=profile.context.saved)
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
            return work.outcome(agent.report, stop)
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
            try:
                self.close_background(keep_browser=not stop.is_set())
            except OSError as error:
                fault = failure_info(error)
                self.report_error(f"Agent browser cleanup failed: {fault.kind}; {' > '.join(fault.locations)}")
                log.problem("The agent browser could not close; its background pages may still be using memory.")
            with contextlib.suppress(OSError):
                self.record({"durable": True, "seconds": round(time.monotonic() - started, 1), **agent.timings})
