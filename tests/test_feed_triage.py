"""The automatic feed handles evidence, noise and revisions without claiming actions happened."""

import json
from dataclasses import replace
from datetime import date

from assistant.agent_session import Session
from assistant.communications import Conversation, Feed, Message, TeamsActivity, Update, UpdateKind
from assistant.feed_contracts import (
    STORED_BOARD,
    CompleteItem,
    DismissItem,
    Disposition,
    ForgetRule,
    ProposedSolution,
    QuietItem,
    RejectProposal,
    ReviseProposal,
    SaveRule,
)
from assistant.feed_items import WorkItem, action_spans, observed, text
from assistant.feed_sources import Excerpt, triage_evidence
from assistant.feed_triage import (
    Assessment,
    Board,
    EditObservation,
    applied,
    decode,
    edited,
    reconcile,
    restored,
    saved,
    unassessed,
)
from assistant.llm import Json
from assistant.notifications import Stack, advance
from tests.feed_source_fixture import captured
from tests.json_fixture import json_object, json_rows
lazy from assistant.feed_agent_tools import validated
lazy from assistant.feed_triage import batch_for, proposal_revision, reconsidered, selected, solution_task


def output(*groups: tuple[list[str], str]) -> str:
    payload: dict[str, Json] = {
        "items": [
            {
                "sources": list[Json](refs),
                "disposition": kind,
                "title": "Review the budget",
                "summary": "Anna needs your review.",
                "suggestion": "Check the totals before replying.",
                "solutions": [
                    {"label": "Check totals", "kind": "check", "detail": "Compare totals against the budget."},
                    {"label": "Draft reply", "kind": "draft", "detail": "Prepare a reply explaining the review."},
                ],
                "priority": 1,
            }
            for refs, kind in groups
        ]
    }
    return json.dumps(payload)


def test_reactions_never_become_cards_and_grouped_requests_have_no_manual_action_strip() -> None:
    feed = Feed(
        conversations=(Conversation("budget", "Budget"),),
        followed=("budget",),
        messages=(Message("budget", "one", "Anna", "Can you review the budget?", 1, 1),),
        updates=(Update(TeamsActivity("reaction"), "Anna liked a message", "👍", "Teams", 2, UpdateKind.REACTION),),
    )
    candidates = triage_evidence(feed, ())
    board = reconcile(Board(enabled=True), candidates)
    batch = unassessed(board, candidates)
    assert len(batch) == 1 and board.reactions == 1
    board = applied(board, decode(output(([batch[0].identity], "action")), batch), candidates)
    rows = observed(Session(triage=board, communications=feed))
    assert len(rows) == 1 and rows[0].title == "Review the budget"
    assert "Check the totals before replying." in text(rows[0])
    assert not board.actions[0].question and board.actions[0].solutions[0].label == "Check totals"
    assert not action_spans(rows[0])
    assert len(advance(Stack(), Session(triage=board, communications=feed), 3).toasts) == 1


def test_model_must_cover_exact_sources_once_and_cannot_complete_work() -> None:
    first = captured("one", Excerpt("Budget", "Please review.", 1))
    second = captured("two", Excerpt("Budget review", "Same request.", 2))
    batch = (first, second)
    grouped = decode(output(([first.identity, second.identity], "action")), batch)
    assert len(grouped) == 1 and len(grouped[0].references) == 2
    for raw in (
        output(([first.identity], "action")),
        output(([first.identity, first.identity], "action")),
        output(([first.identity, "invented"], "action")),
        output(([first.identity, second.identity], "done")),
        output(([first.identity, second.identity], "dismissed")),
    ):
        try:
            decode(raw, batch)
        except ValueError:
            pass
        else:
            raise AssertionError("Invalid model output was accepted.")


def test_revision_change_rejects_stale_results_and_completed_work_does_not_reappear_on_poll() -> None:
    first = captured("one", Excerpt("Budget", "Please review.", 1))
    current = replace(first, revision="new-revision", body="Updated figures need review.")
    assessment = decode(output(([first.identity], "action")), (first,))
    board = applied(Board(enabled=True), assessment, (first,))
    done = edited(board, CompleteItem(assessment[0].identity), EditObservation((first,), 2))
    assert not reconcile(done, (first,)).actions and not unassessed(done, (first,))
    assert unassessed(reconcile(done, (current,)), (current,)) == (current,)
    assert not applied(Board(enabled=True), assessment, (current,)).actions
    assert restored(saved(done)).items[0].disposition is Disposition.DONE
    assert not unassessed(reconcile(restored(saved(done)), ()), (first,))


def test_explicit_voice_feedback_reclassifies_open_and_quiet_work_and_survives_restore() -> None:
    first = captured("one", Excerpt("Budget", "Thanks.", 1))
    board = applied(Board(enabled=True), decode(output(([first.identity], "quiet")), (first,)), (first,))
    assert not board.actions and not unassessed(board, (first,))
    board = edited(board, SaveRule("Keep routine budget acknowledgements quiet."), EditObservation((first,), 2))
    assert unassessed(board, (first,)) == (first,)
    assert restored(saved(board)).rules == board.rules
    forgotten = edited(board, ForgetRule(board.rules[0]), EditObservation((first,), 3))
    assert not forgotten.rules
    try:
        edited(board, CompleteItem("invented"), EditObservation((first,), 3))
    except ValueError:
        pass
    else:
        raise AssertionError("A stale proposal was handled.")


def test_new_related_arrival_can_join_an_existing_action_without_duplicate_cards() -> None:
    first = captured("one", Excerpt("Budget", "Please review.", 1))
    second = captured("two", Excerpt("Budget reminder", "Reminder to review.", 2))
    board = applied(Board(enabled=True), decode(output(([first.identity], "action")), (first,)), (first,))
    candidates = (first, second)
    batch = batch_for(reconcile(board, candidates), candidates)
    assert {item.identity for item in batch} == {first.identity, second.identity}
    board = applied(board, decode(output(([first.identity, second.identity], "action")), batch), candidates)
    assert len(board.actions) == 1 and len(board.actions[0].references) == 2 and board.pending == 0


def test_proposed_work_survives_source_disappearance_and_restart_without_becoming_live_evidence() -> None:
    first = captured("one", Excerpt("Review", "Please review the totals.", 1))
    board = applied(Board(enabled=True), decode(output(([first.identity], "action")), (first,)), (first,))
    offline = reconcile(restored(saved(board)), ())
    assert offline.actions == board.actions
    # Defect: filtering feedback discards work that can no longer be re-evaluated, or keeps stale live assessments.
    rule = SaveRule("Prioritize blocked colleagues.")
    assert edited(offline, rule, EditObservation((), 2)).actions == board.actions
    assert not edited(board, rule, EditObservation((first,), 2)).actions
    changed = replace(first, revision="new", body="The review is cancelled.")
    assert not reconcile(offline, (changed,)).actions


def test_dismissal_survives_poll_restart_and_filter_feedback_but_new_evidence_gets_reviewed() -> None:
    first = captured("one", Excerpt("Budget", "Please review.", 1))
    board = applied(Board(enabled=True), decode(output(([first.identity], "action")), (first,)), (first,))
    dismissed = edited(board, DismissItem(board.actions[0].identity), EditObservation((first,), 2))
    restarted = reconcile(restored(saved(dismissed)), (first,))
    feedback = edited(restarted, SaveRule("Prioritize work that blocks a colleague."), EditObservation((first,), 3))
    assert not feedback.actions and not unassessed(feedback, (first,))
    assert feedback.items[0].disposition is Disposition.DISMISSED
    changed = replace(first, revision="new-evidence", body="The deadline is now tomorrow.")
    assert unassessed(reconcile(feedback, (changed,)), (changed,)) == (changed,)
    assert board.items[0].disposition is not Disposition.DONE


def test_top_work_is_selected_by_importance_and_dismissal_advances_the_queue_without_losing_backlog() -> None:
    items = tuple(
        Assessment(
            str(index),
            ((str(index), "revision"),),
            f"Work {index}",
            "Needs review",
            "Review it",
            "",
            2 if index == 0 else 1 if index < 3 else 0,
            index + 1,
        )
        for index in range(8)
    )
    board = Board(enabled=True, items=items)
    session = Session(triage=board)
    stack = advance(Stack(), session, 100)
    assert [toast.content.title for toast in stack.toasts if isinstance(toast.content, WorkItem)] == ["Work 0", "Work 1", "Work 2"]
    assert len(board.actions) == 8
    dismissed = edited(board, DismissItem("0"), EditObservation((), 1))
    next_stack = advance(stack, replace(session, triage=dismissed), 10000)
    assert [toast.content.title for toast in next_stack.toasts if isinstance(toast.content, WorkItem)] == ["Work 1", "Work 2", "Work 3"]
    assert len(dismissed.actions) == 7
    reprioritized = edited(dismissed, ReviseProposal(item="7", text="Handle the blocker first.", priority=2), EditObservation((), 2))
    assert reprioritized.actions[0].identity == "7"


def test_solutions_are_revision_bound_persisted_and_untrusted_details_cannot_expand_the_recipe() -> None:
    source = captured("budget", Excerpt("Budget", "Please review.", 1))
    item = decode(output(([source.identity], "action")), (source,))[0]
    board = restored(saved(Board(enabled=True, items=(item,))))
    assert board.actions == (item,) and saved(board).items
    chosen, option = selected(board, item.identity, proposal_revision(item), "1")
    task, prompt = solution_task(chosen, option)
    assert "Investigate the relevant facts" in prompt and "preparation only" in prompt
    assert solution_task(chosen, option) == (task, prompt)
    changed = replace(item, summary="A different request now.")
    try:
        selected(replace(board, items=(changed,)), item.identity, proposal_revision(item), "1")
    except ValueError:
        pass
    else:
        raise AssertionError("A stale choice was accepted.")
    legacy = replace(item, solutions=())
    assert unassessed(Board(enabled=True, items=(legacy,)), (source,)) == (source,)
    assert not unassessed(Board(enabled=True, items=(replace(legacy, disposition=Disposition.DISMISSED),)), (source,))


def test_action_solutions_require_valid_distinct_bounded_choices() -> None:
    source = captured("one", Excerpt("Review", "Please review.", 1))
    options: tuple[list[Json], ...] = (
        [],
        [{"label": "Send", "kind": "send", "detail": "Send it now."}],
        [{"label": "Check", "kind": "check", "detail": ""}],
        [{"label": "Check", "kind": "check", "detail": "Check it."}] * 2,
        [{"label": str(index), "kind": "check", "detail": "Check it."} for index in range(4)],
    )
    for solutions in options:
        payload = json_object(output(([source.identity], "action")))
        json_rows(payload["items"])[0]["solutions"] = solutions
        try:
            decode(json.dumps(payload), (source,))
        except ValueError:
            pass
        else:
            raise AssertionError("Invalid solution options accepted.")


def test_voice_correction_replaces_solutions_immediately_even_without_live_sources() -> None:
    source = captured("one", Excerpt("Review", "Please review.", 1))
    item = decode(output(([source.identity], "action")), (source,))[0]
    board = Board(enabled=True, items=(item,))
    revised = edited(
        board,
        ReviseProposal(
            item=item.identity,
            text="Prepare a short clarification.",
            question="Which totals need review?",
            solutions=(ProposedSolution("Draft clarification", "draft", "Ask which totals need review."),),
        ),
        EditObservation((), 2),
    )
    assert revised.actions[0].solutions[0].label == "Draft clarification"
    assert revised.actions[0].question == "Which totals need review?"
    assert revised.history[-1].kind == "propose" and revised.history[-1].text == "Prepare a short clarification."
    assert restored(saved(revised)).actions == revised.actions
    fallback = edited(board, ReviseProposal(item=item.identity, text="Investigate the discrepancy."), EditObservation((), 2))
    assert fallback.actions[0].solutions[0].detail == "Investigate the discrepancy."


def test_meaningful_rejection_records_reason_and_revision_without_completing_or_sending() -> None:
    source = captured("request", Excerpt("Budget", "Can you approve this budget?", 1))
    item = decode(output(([source.identity], "action")), (source,))[0]
    board = Board(enabled=True, items=(item,))
    arguments: dict[str, Json] = {
        "operation": "reject",
        "item": item.identity,
        "revision": proposal_revision(item),
        "text": "I cannot approve this because the figures are incomplete.",
    }
    match validated("work_feed_update", arguments):
        case RejectProposal() as rejection:
            pass
        case _:
            raise AssertionError("Filtering feedback became a work reply.")
    observation = EditObservation((source,), 2)
    changed = edited(board, rejection, observation)
    assert not changed.actions and changed.items[0].disposition is Disposition.REJECTED
    assert "figures are incomplete" in changed.items[0].decision
    assert restored(saved(changed)).items == changed.items
    assert [(entry.kind, entry.revision, entry.at) for entry in changed.history] == [("reject", proposal_revision(item), 2)]
    assert edited(changed, rejection, observation).history == changed.history, "A retried edit recorded a second decision."
    assert edited(changed, SaveRule("Ignore routine reminders."), observation).items == changed.items
    assert not unassessed(reconcile(changed, (source,)), (source,))
    try:
        edited(board, replace(rejection, revision="stale"), observation)
    except ValueError:
        pass
    else:
        raise AssertionError("A stale proposal was rejected.")
    duplicate: Json = {"label": "Check", "kind": "check", "detail": "Check it."}
    invalid: tuple[tuple[str, dict[str, Json]], ...] = (
        ("work_feed_update", {**arguments, "text": " "}),
        ("work_feed_update", {"operation": "choose", "item": item.identity, "revision": proposal_revision(item), "choice": "1"}),
        (
            "work_feed_update",
            {
                "operation": "propose",
                "item": item.identity,
                "text": "Check.",
                "solutions": [duplicate, duplicate],
            },
        ),
        ("work_feed_update", {"operation": "rule", "text": "Keep budget notices quiet.\x00"}),
        ("work_feed_answer", {"request_id": "console", "question_index": 32, "text": "Revenue"}),
    )
    for tool, values in invalid:
        try:
            validated(tool, values)
        except ValueError:
            pass
        else:
            raise AssertionError(f"Invalid {tool} arguments were accepted: {values}")


def test_context_refresh_reopens_automatic_quiet_work_but_keeps_explicit_handling() -> None:
    # Defect: a request hidden because related work was underway stays hidden
    # after that work fails; refreshing context also revives an explicit user quiet.
    today = date(2026, 10, 29)
    automatic = captured("automatic", Excerpt("Atlas", "Review the variance.", 1))
    explicit = captured("explicit", Excerpt("Orion", "Routine update.", 1))
    quiet = replace(decode(output(([automatic.identity], "quiet")), (automatic,))[0], reviewed_on=today)
    proposal = replace(decode(output(([explicit.identity], "action")), (explicit,))[0], reviewed_on=today)
    handled = edited(Board(enabled=True, items=(proposal,)), QuietItem(proposal.identity), EditObservation((), 2))
    board = Board(enabled=True, items=(quiet, *handled.items))
    assert not unassessed(board, (automatic, explicit), today=today)
    refreshed = reconsidered(restored(saved(board)))
    assert unassessed(refreshed, (automatic, explicit), today=today) == (automatic,)
    assert refreshed.items[1].disposition is Disposition.USER_QUIET
    assert refreshed.items[1] == handled.items[0]
    filtered = edited(refreshed, SaveRule("Prioritize a different project."), EditObservation((automatic, explicit), 3))
    assert filtered.items == handled.items


def test_a_board_saved_before_origins_were_captured_keeps_its_rules_and_items() -> None:
    # Defect: the added origins field makes older saved boards fail validation, discarding rules and history.
    source = captured("one", Excerpt("Budget", "Please review.", 1))
    board = edited(
        applied(Board(enabled=True), decode(output(([source.identity], "action")), (source,)), (source,)),
        SaveRule("Keep routine updates quiet."),
        EditObservation((), 2),
    )
    assert board.items and board.history
    stored = STORED_BOARD.dump_python(saved(board), mode="json")
    for item in stored["items"]:
        del item["origins"]
    restarted = restored(STORED_BOARD.validate_python(stored))
    assert restarted.rules == board.rules and restarted.history == board.history and [item.identity for item in restarted.items] == [item.identity for item in board.items]
    assert all(item.origins == () for item in restarted.items)
