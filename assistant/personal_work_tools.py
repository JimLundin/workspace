"""Agent contracts for the persistent My work catalog."""

from collections.abc import Callable, Mapping
from typing import Final

from assistant.agent_tools import Args, Display, Output, Session, Tool
from assistant.business_tools import spec
from assistant.llm import Json, ToolSpec
from assistant.work_bridge_contracts import BridgeCommand
from automation.actions import Change, Classification, Observation, target
from automation.personal_work import (
    PERSONAL_REQUEST,
    PERSONAL_RESPONSE,
    AddDocument,
    AddWebPage,
    DismissWork,
    DocumentAdded,
    ListSources,
    ListWork,
    PersonalRequest,
    RestoreWork,
    SaveWork,
    UnlinkWork,
    WorkRefused,
    WorkSaved,
)
from automation.task import ActionNotApplied, ActionUncertain, ActionVerified

INSTRUCTIONS = """My work is the user's persistent representation of ongoing work, connecting Outlook conversations, Teams
conversations, Kanban tickets and documents. Sources can contain observed message pieces; keep the conversation
connection when its whole discussion supplies context, and use a child source only when that specific piece is relevant.
It is distinct from agent execution tasks and from transient feed proposals.
Each work definition is a context/container on the local desktop canvas, your primary work surface. Classifying an
existing ticket is metadata, not an additional finding or completed action. Keep the actual sources, questions, findings,
drafts and substantive outcomes in that same context; do not create another work definition to record a request or tool call.
Independently research the next useful step,
fetch the relevant browser evidence and build on the same work thread. Routine app arrivals are context, not user alerts.
Use ask_user when essential input cannot be discovered or inferred. The clarification appears on the canvas; after the
answer, continue this same work and update its summary, next step and evidence. Useful research results extend the
context; requests and action history stay in execution history. Distinguish a saved draft from a verified external change. Work classification
stays quiet; meaningful results and state changes can provide canvas redirects.
For questions about the user's overall work, first read work_items_list and work_items_sources. Use the exact saved work_id,
revision and source ids. One source can contribute to several work threads. Connections are maintained automatically from
observed browser evidence; missing rows are not proof of deletion or completion. Explain uncertainty and source coverage.
work_items_save creates or updates a personal work definition and its explicit connections. Read before updating and include
all wanted links. Use work_items_unlink to correct an unrelated source; the correction survives automatic reviews.
Saving a work definition, marking it done or suggesting a next step does not perform the underlying work. Only mark done
when the user asks or the observed result establishes completion. Never send a message or change a ticket just to update My work.
"""

SPECS: Final = (
    spec(
        "work_items_add_web_page",
        "Save a researched HTTPS web page with its original URL and useful captured excerpt. Optional work_id connects it to that work. "
        "Save pages that provide evidence, not every navigation attempt.",
        AddWebPage,
    ),
    spec(
        "work_items_dismiss",
        "Dismiss incorrectly assigned or irrelevant work locally with its exact current revision and the user's reason. "
        "Automatic reviews remember it. Only use when the user directs dismissal.",
        DismissWork,
    ),
    spec("work_items_restore", "Restore a previously dismissed work context by its exact work_id when the user asks.", RestoreWork),
    spec(
        "work_items_add_document",
        "Register a local document (absolute Windows path) or HTTPS document link on the canvas. "
        "Use a factual title and bounded excerpt; optional work_id connects the document to that work. "
        "Registration does not create, edit or publish the underlying file.",
        AddDocument,
    ),
    spec(
        "work_items_list",
        "Read saved personal work with goals, current summaries, next steps, states and associated sources. "
        "Query matches title, goal and project; follow next_offset.",
        ListWork,
    ),
    spec(
        "work_items_sources",
        "Read observed Teams, Outlook and Kanban sources with exact source ids, application identities and bounded excerpts. "
        "Coverage follows rendered browser pages; query can include an exact source or parent id to find conversation pieces. Follow next_offset.",
        ListSources,
    ),
    spec(
        "work_items_save",
        "Create or update a personal piece of work. Updates require work_id and expected_revision from work_items_list. "
        "Supply every wanted source association with its factual reason; source ids must come from work_items_sources. "
        "This updates the personal representation only.",
        SaveWork,
    ),
    spec(
        "work_items_unlink",
        "Correct one unrelated source connection in saved personal work. Requires its exact work_id, source_id and expected_revision. "
        "Automatic reviews remember this correction.",
        UnlinkWork,
    ),
)


def validated(tool: str, arguments: dict[str, Json]) -> PersonalRequest:
    payload: dict[str, Json] = {**arguments, "operation": tool}
    return PERSONAL_REQUEST.validate_python(payload)


def verified(output: str) -> ActionVerified | ActionUncertain | ActionNotApplied:
    match PERSONAL_RESPONSE.validate_json(output):
        case DocumentAdded(source):
            return ActionVerified("Added document reference " + source.id)
        case WorkSaved(work):
            return ActionVerified("Saved personal work " + work.id + " at revision " + str(work.revision))
        case WorkRefused(reason):
            return ActionNotApplied(reason)
        case _:
            return ActionUncertain("The work catalog did not confirm the change.")


def _resources(arguments: Mapping[str, Json]) -> tuple[str, ...]:
    match arguments.get("work_id"):
        case str() as work_id:
            return ("personal-work", target("personal-work", work_id))
        case _:
            return ("personal-work",)


def _classify(spec: ToolSpec) -> Callable[[Mapping[str, Json]], Classification]:
    match spec.name:
        case "work_items_list" | "work_items_sources":
            return lambda arguments: Observation(_resources(arguments))
        case (
            "work_items_add_web_page"
            | "work_items_dismiss"
            | "work_items_restore"
            | "work_items_add_document"
            | "work_items_save"
            | "work_items_unlink"
        ):
            return lambda arguments: Change(_resources(arguments))
        case _:
            raise ValueError(f"The personal work tool {spec.name} has no classification.")


class PersonalWork:
    __slots__ = ("request", "session")

    def __init__(self, session: Session, request: Callable[[BridgeCommand], str]) -> None:
        self.session, self.request = session, request

    def tools(self) -> tuple[Tool, ...]:
        return tuple(Tool(spec, self.catalog, _classify(spec), Display.PRIVATE) for spec in SPECS)

    def catalog(self, args: Args) -> Output:
        request = validated(args.tool, args.values)
        return self.session.effect(args.operation, lambda: Output(self.request(request)), lambda output: verified(output.text))
