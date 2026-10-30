"""Bounded autonomous investigations driven by changed external evidence."""

import hashlib
from collections.abc import Sequence
from dataclasses import replace
from typing import assert_never

from pydantic import TypeAdapter

from assistant.canvas_activity import ROOT_CONTEXT, CanvasInstruction, CanvasResearch, CanvasRun
from assistant.work_canvas_model import CanvasDocument
from automation.personal_work import Catalog, SourceKind, WorkState, WorkThread
from automation.task import Task, phase

_EVIDENCE = TypeAdapter(tuple[tuple[str, str], ...])


def retained(document: CanvasDocument, tasks: Sequence[Task]) -> CanvasDocument:
    terminal = frozenset(task.id for task in tasks if phase(task.state) in ("completed", "failed", "cancelled"))
    latest = frozendict((run.work_id, run.task_id) for run in document.runs if run.evidence is not None)
    # Completed contributions already carry their work identity in activity.
    # Retain the latest evidence cursor plus every unresolved/manual binding.
    runs = tuple(
        run
        for run in document.runs
        if (run.work_id != ROOT_CONTEXT or run.task_id not in terminal)
        and (run.evidence is None or run.task_id not in terminal or latest.get(run.work_id) == run.task_id)
    )
    return replace(document, runs=runs)


def evidence(work: WorkThread, catalog: Catalog) -> str | None:
    linked = frozenset(link.source_id for link in work.links)
    included = linked
    # Rendered child emails/messages can change while their conversation's
    # summary stays the same. Documents we register ourselves do not retrigger.
    while True:
        revised = included | frozenset(source.id for source in catalog.sources if source.parent_id in included)
        if revised == included:
            break
        included = revised
    observed = tuple(
        sorted(
            (source.id, source.revision)
            for source in catalog.sources
            if source.id in included and source.kind not in (SourceKind.DOCUMENT, SourceKind.WEB_PAGE)
        )
    )
    return hashlib.sha256(_EVIDENCE.dump_json(observed)).hexdigest() if observed else None


def pending(catalog: Catalog, document: CanvasDocument, tasks: Sequence[Task]) -> tuple[CanvasRun, ...]:
    known = frozendict((task.id, phase(task.state)) for task in tasks)
    busy = frozenset(run.work_id for run in document.runs if known.get(run.task_id) not in ("completed", "failed", "cancelled"))
    automatic = sum(run.evidence is not None and known.get(run.task_id) not in ("completed", "failed", "cancelled") for run in document.runs)
    capacity = max(0, 3 - automatic)
    # Bindings are retained by the execution journal's bounded watcher. Avoid
    # silently losing question routing when its retention budget is exhausted.
    capacity = min(capacity, max(0, 500 - len(document.runs)))
    candidates: tuple[CanvasRun, ...] = ()
    for work in catalog.works:
        if work.definition.state is not WorkState.ACTIVE or work.id in busy:
            continue
        current = evidence(work, catalog)
        if current is None or any(run.work_id == work.id and run.evidence == current for run in document.runs):
            continue
        identity = hashlib.sha256((work.id + "\0" + current).encode()).hexdigest()
        candidates = (*candidates, CanvasRun("canvas:auto:" + identity, work.id, CanvasResearch(current)))
        if len(candidates) == capacity:
            break
    return candidates if capacity else ()


def instruction_prompt(run: CanvasRun) -> str:
    """Keep the user's exact direction durable alongside its canvas context."""
    match run.intent:
        case CanvasInstruction(text=instruction):
            context = (
                "Its scope is the whole canvas. Read work_canvas_read to inspect the existing bubbles before acting. "
                if run.work_id == ROOT_CONTEXT
                else f"Its context bubble is {run.work_id}. Read work_canvas_read to inspect that bubble, "
                "its ancestors, connected references and contents before acting. "
            )
            return (
                instruction + "\n\n"
                "This instruction was submitted from the local desktop canvas. "
                + context
                + "There is one shared canvas; organize work using nested bubbles on it. "
                "Use the available browser and document tools to investigate, and work_canvas_update to add only meaningful "
                "findings, references, drafts and questions to the appropriate bubbles. Keep routine fetch attempts in execution history. "
                "The request itself and reports of actions taken are execution history, not canvas content. "
                "Editing positions or relationships changes the existing canvas directly without adding a report bubble. "
                "For substantive new work, choose or create a meaningful context, and place the useful results there. "
                "Ask for clarification when needed, and continue the same work after the user answers. "
                "The user's instruction above determines what actions are authorized."
            )
        case CanvasResearch():
            raise ValueError("A research run has no user instruction.")
        case _:
            assert_never(run.intent)
