"""The task tool family: the durable task's questions, action records, reconciliation and the current time."""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Annotated, Final

from pydantic import Field, TypeAdapter

from assistant.agent_tools import NO_ARGUMENTS, Args, ArgumentError, Display, NoArguments, Output, Session, Tool, argument_spec, fixed, typed_run
from automation.actions import Evidence, Observation
from automation.execution import Proof, Reconciliation, WorkExecution

type Text = Annotated[str, Field(strict=True)]


@dataclass(frozen=True, slots=True)
class QuestionArguments:
    question: Text


@dataclass(frozen=True, slots=True)
class ReconcileArguments:
    action_id: Text
    observation_id: Text
    applied: Annotated[bool, Field(strict=True)] = field(kw_only=True)


_QUESTION: Final = TypeAdapter(QuestionArguments)
_RECONCILE: Final = TypeAdapter(ReconcileArguments)


class TaskTools:
    __slots__ = ("clock", "session", "work")

    def __init__(self, session: Session, work: WorkExecution, clock: Callable[[], datetime]) -> None:
        self.session, self.work, self.clock = session, work, clock

    def tools(self, proof: Callable[[str], Proof], display: Display) -> tuple[Tool, ...]:
        """`proof` is each tool family's reconciliation rule; `display` applies to the task's own records."""
        unobserved = fixed(Observation((), Evidence.NONE))
        return (
            Tool(
                argument_spec(
                    "get_current_time",
                    "Read the current local date/time with UTC offset and timezone, UTC time and Unix timestamp. "
                    "Use a fresh observation for time-sensitive decisions; the prompt time is only a starting snapshot.",
                    NO_ARGUMENTS,
                ),
                typed_run(NO_ARGUMENTS, self.get_current_time),
                fixed(Observation((), Evidence.GENERAL)),
                Display.PUBLIC,
            ),
            Tool(
                argument_spec(
                    "ask_user",
                    "Ask for essential missing information that you cannot find or reasonably infer. Do not use for routine approval.",
                    _QUESTION,
                ),
                typed_run(_QUESTION, self.ask_user),
                unobserved,
                display,
            ),
            Tool(
                argument_spec(
                    "work_actions",
                    "Inspect this durable task's action records and unresolved operations. "
                    "Recorded tool success alone does not prove that the requested outcome was achieved.",
                    NO_ARGUMENTS,
                ),
                typed_run(NO_ARGUMENTS, self.work_actions),
                unobserved,
                display,
            ),
            Tool(
                argument_spec(
                    "reconcile_action",
                    "Verify a returned action or resolve an uncertain action after inspecting its actual target. "
                    "Use the action ID from work_actions and an observation_id from a successful inspection in this run. "
                    "Set applied=true only when that fresh observation establishes the intended effect; applied=false requires "
                    "proof it was not applied. File writes additionally require an exact content digest match.",
                    _RECONCILE,
                ),
                typed_run(_RECONCILE, lambda args, request: self.reconcile_action(request, proof)),
                unobserved,
                display,
            ),
        )

    def get_current_time(self, args: Args, _request: NoArguments) -> Output:
        """The tool owner samples the clock once and publishes that observation."""

        def read() -> Output:
            observed = self.clock().astimezone()
            return Output(
                f"Local time: {observed.isoformat(timespec='seconds')}\n"
                f"Timezone: {observed.tzname()}\n"
                f"UTC time: {observed.astimezone(UTC).isoformat(timespec='seconds')}\n"
                f"Unix timestamp: {observed.timestamp():.3f}"
            )

        return self.session.effect(args.operation, read)

    def ask_user(self, _args: Args, request: QuestionArguments) -> Output:
        answer = self.work.ask(request.question)
        return Output(answer if answer else "The user didn't answer.", ok=bool(answer))

    def work_actions(self, _args: Args, _request: NoArguments) -> Output:
        return Output(self.work.describe_actions())

    def reconcile_action(self, arguments: ReconcileArguments, proof: Callable[[str], Proof]) -> Output:
        request = Reconciliation(arguments.action_id, arguments.observation_id, applied=arguments.applied)
        try:
            return Output(self.work.reconcile(request, proof))
        except ValueError as error:
            raise ArgumentError(str(error)) from error
