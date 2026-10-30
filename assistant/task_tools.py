"""The task tool family: the durable task's questions, action records, reconciliation and the current time."""

from collections.abc import Callable
from datetime import UTC, datetime

from assistant.agent_tools import BOOL, TEXT, Args, ArgumentError, Display, Output, Session, Tool, fixed, schema
from assistant.llm import tool_spec
from automation.actions import Evidence, Observation
from automation.execution import Proof, Reconciliation, WorkExecution


class TaskTools:
    __slots__ = ("clock", "session", "work")

    def __init__(self, session: Session, work: WorkExecution, clock: Callable[[], datetime]) -> None:
        self.session, self.work, self.clock = session, work, clock

    def tools(self, proof: Callable[[str], Proof], display: Display) -> tuple[Tool, ...]:
        """`proof` is each tool family's reconciliation rule; `display` applies to the task's own records."""
        unobserved = fixed(Observation((), Evidence.NONE))
        return (
            Tool(
                tool_spec(
                    "get_current_time",
                    "Read the current local date/time with UTC offset and timezone, UTC time and Unix timestamp. "
                    "Use a fresh observation for time-sensitive decisions; the prompt time is only a starting snapshot.",
                    schema({}, ()),
                ),
                self.get_current_time,
                fixed(Observation((), Evidence.GENERAL)),
                Display.PUBLIC,
            ),
            Tool(
                tool_spec(
                    "ask_user",
                    "Ask for essential missing information that you cannot find or reasonably infer. Do not use for routine approval.",
                    schema({"question": TEXT}, ("question",)),
                ),
                self.ask_user,
                unobserved,
                display,
            ),
            Tool(
                tool_spec(
                    "work_actions",
                    "Inspect this durable task's action records and unresolved operations. "
                    "Recorded tool success alone does not prove that the requested outcome was achieved.",
                    schema({}, ()),
                ),
                self.work_actions,
                unobserved,
                display,
            ),
            Tool(
                tool_spec(
                    "reconcile_action",
                    "Verify a returned action or resolve an uncertain action after inspecting its actual target. "
                    "Use the action ID from work_actions and an observation_id from a successful inspection in this run. "
                    "Set applied=true only when that fresh observation establishes the intended effect; applied=false requires "
                    "proof it was not applied. File writes additionally require an exact content digest match.",
                    schema({"action_id": TEXT, "observation_id": TEXT, "applied": BOOL}, ("action_id", "observation_id", "applied")),
                ),
                lambda args: self.reconcile_action(args, proof),
                unobserved,
                display,
            ),
        )

    def get_current_time(self, args: Args) -> Output:
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

    def ask_user(self, args: Args) -> Output:
        answer = self.work.ask(args.text("question"))
        return Output(answer if answer else "The user didn't answer.", ok=bool(answer))

    def work_actions(self, _: Args) -> Output:
        return Output(self.work.describe_actions())

    def reconcile_action(self, args: Args, proof: Callable[[str], Proof]) -> Output:
        if not isinstance(args.values.get("applied"), bool):
            raise ArgumentError("applied must be true or false.")
        request = Reconciliation(args.text("action_id"), args.text("observation_id"), applied=args.flag("applied"))
        try:
            return Output(self.work.reconcile(request, proof))
        except ValueError as error:
            raise ArgumentError(str(error)) from error
