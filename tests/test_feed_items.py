"""Work sources and agent turns share one ordered, paged floating projection."""

from dataclasses import replace

import assistant.notification_text
from assistant.agent_session import Begin, Said, Session, transition
from assistant.communications import Update, WindowsNotice
from assistant.console_requests import Provider, request
from assistant.feed_items import WorkItem, action_spans, body_spans, expanded_spans, observed
from assistant.feed_origin import FeedRequest
from assistant.inbox import Query, Source
from assistant.notifications import MAX_VISIBLE, Stack, Turn, advance, body, observe
from assistant.system_notices import NoticeKey
from tests.test_console_inbox import event
lazy from assistant.communications import Acknowledgement, Conversation, Feed, Message, Status, TeamsActivity, UpdateKind, handle, update_fingerprint
lazy from assistant.feed_items import reactions
lazy from assistant.feed_origin import App
lazy from assistant.feed_triage import Assessment, Board, collect


def test_notification_projection_shares_evidence_for_proposals_and_attached_turns() -> None:
    # Defect: each proposal and attached turn rescans all source/handling records on Qt's thread.
    feed = Feed(
        updates=tuple(
            Update(WindowsNotice(NoticeKey(index, 1), "outlook"), f"Figures {index}", f"Evidence {index}", "Outlook", index + 1) for index in range(3)
        )
    )
    candidates = collect(feed, ())
    proposals = tuple(
        Assessment(str(index), ((source.identity, source.revision),), source.title, "Compare totals", "Prepare a draft", "", 1, index + 1)
        for index, source in enumerate(candidates)
    )
    proposals = (proposals[0], replace(proposals[1], references=(*proposals[0].references, *proposals[1].references)), proposals[2])
    session = Session(communications=feed, triage=Board(enabled=True, items=proposals))
    session = transition(session, Begin("Review figures", 10, source=FeedRequest("0", proposals[0].title)))
    items = observe(session)
    turn = next(item for item in items if isinstance(item, Turn))
    assert turn.origin is not None and turn.origin.item == proposals[0] and turn.origin.evidence == (candidates[0],)
    rows = tuple(item for item in items if isinstance(item, WorkItem))
    assert {row.item.identity for row in rows if isinstance(row.item, Assessment)} == {"1", "2"}
    assert {source.identity for row in rows for source in row.evidence} == {source.identity for source in candidates}
    shared = next(row for row in rows if isinstance(row.item, Assessment) and row.item.identity == "1")
    assert turn.origin.evidence[0] is shared.evidence[0], "A snapshot must reuse its validated evidence across all proposals."


def test_expansion_shows_only_matching_source_revisions_and_labels_missing_originals() -> None:
    update = Update(WindowsNotice(NoticeKey(80, 2), "outlook"), "Forecast", "Original captured figures", "Outlook", 3)
    feed = Feed(updates=(update,))
    source = collect(feed, ())[0]
    proposal = Assessment(
        "forecast", ((source.identity, source.revision),), "Review the forecast", "The figures need review.", "Check the totals.", "", 1, 3
    )
    session = Session(communications=feed, triage=Board(enabled=True, items=(proposal,)))
    row = observed(session)[0]
    assert "".join(span.text for span in assistant.notification_text.spans(row, expanded=False)) == proposal.title + "\n" + proposal.suggestion
    assert update.text in "".join(span.text for span in expanded_spans(row))
    newer = replace(session, communications=replace(feed, updates=(replace(update, text="Different, unreviewed figures"),)))
    detail = "".join(span.text for span in expanded_spans(observed(newer)[0]))
    assert "Different, unreviewed figures" not in detail and "no longer available" in detail
    assert proposal.summary in detail


def test_grouped_work_keeps_app_identity_and_rich_body_links_without_an_action_footer() -> None:
    feed = Feed(
        conversations=(Conversation("chat", "Planning"),),
        followed=("chat",),
        messages=(Message("chat", "one", "Anna", "Review the figures", 2, 2),),
        updates=(Update(WindowsNotice(NoticeKey(1, 2), "outlook"), "Review reminder", "Please review", "Outlook", 3),),
    )
    candidates = collect(feed, ())
    proposal = Assessment(
        "group",
        tuple((item.identity, item.revision) for item in candidates),
        "Review the figures",
        "Read **the totals** at [the report](https://example.test/report). Then check `FY27`.",
        "- Compare both sheets\n- Prepare a draft",
        "Shall I draft it?",
        1,
        3,
    )
    row = observed(Session(communications=feed, triage=Board(enabled=True, items=(proposal,))))[0]
    assert [origin.app for origin in row.origins] == [App.TEAMS, App.OUTLOOK]
    body = body_spans(row)
    assert any(span.link == "https://example.test/report" for span in body)
    assert any("bold" in span.tags and "the totals" in span.text for span in body)
    assert any("code" in span.tags and span.text == "FY27" for span in body)
    assert "Then check" in "".join(span.text for span in body)
    assert any(span.hanging == "• " for span in body)
    assert not any("feed_question" in span.tags for span in body)
    assert not action_spans(row)


def test_reactions_share_one_compact_strip_and_disappear_after_exact_handling() -> None:
    updates = (
        Update(TeamsActivity("one"), "Anna liked your message", "A preview", "Teams", 1, UpdateKind.REACTION),
        Update(TeamsActivity("two"), "Alex reacted", "Like\nA preview", "Teams", 2, UpdateKind.REACTION),
        Update(TeamsActivity("three"), "Morgan reacted with Laugh", "A preview", "Teams", 3, UpdateKind.REACTION),
    )
    feed = Feed(updates=updates)
    marks, detail = reactions(Session(communications=feed))
    assert marks == "👍 2  😂" and "Anna liked your message" in detail
    assert reactions(Session(communications=handle(feed, tuple(Acknowledgement(item.key, update_fingerprint(item)) for item in updates)))) == ("", "")


def test_windows_teams_and_console_requests_join_agent_bubbles_with_exact_source_links() -> None:
    # Build the source fixture here; native fixture modules cannot load off Windows.
    feed = Feed(
        status=Status.CONNECTED,
        conversations=(Conversation("chat", "Planning"),),
        followed=("chat",),
        messages=(Message("chat", "one", "Anna", "Review the figures", 2, 2),),
        updates=(Update(WindowsNotice(NoticeKey(1, 2), "owned"), "Friday review", "Please review", "Outlook", 3),),
    )
    state = transition(Session(identity="one", communications=feed), Begin("Help with my work", 1))
    state = transition(state, Said("Here is the plan.", 4))
    state = replace(state, console_requests=(request(Provider.CLAUDE, event(Provider.CLAUDE), "owned", 5),))
    stack = advance(Stack(), state, 100)
    assert len(stack.toasts) <= MAX_VISIBLE
    source = [toast.content for toast in stack.toasts if isinstance(toast.content, WorkItem)]
    assert len(source) == 3
    assert any("Here is the plan." in body(toast.content) for toast in stack.toasts)
    assert {item.key.source for item in source} == {"chat", "windows", "console"}
    assert any(span.link.startswith("workspace://console-option?") for row in source for span in action_spans(row) if span.link)
    assert any(span.link.startswith("workspace://help?chat=chat") for row in source for span in action_spans(row) if span.link)
    assert len(observed(state, Query(Source.MAIL))) == 2  # Mail plus the pending console question.
    question = next(row for row in source if row.key.source == "console")
    assert "Which sheet?" in "".join(span.text for span in body_spans(question))
    assert any("Revenue" in span.text for span in action_spans(question))
    assert "".join(span.text for span in action_spans(question)) == "Revenue"
    assert not "".join(span.text for span in body_spans(question)).endswith("\n")


def test_pending_sources_remain_reachable_after_overflow_filtering_and_agent_reset() -> None:
    feed = Feed(
        updates=tuple(
            Update(WindowsNotice(NoticeKey(index, index + 10), "owned"), f"Item {index}", "Fixture", "Mail", index) for index in range(1, 13)
        )
    )
    state = Session(identity="one", communications=feed)
    first = advance(Stack(), state, 100)
    assert len(first.toasts) == 5
    earlier = advance(first, state, 2000, page=1, reveal=True)
    assert earlier.toasts and not {item.key for item in earlier.toasts} & {item.key for item in first.toasts}
    later = advance(earlier, state, 3000)
    assert {item.key for item in later.toasts} == {item.key for item in first.toasts}
    reset = advance(later, replace(state, identity="two"), 4000)
    assert {item.key for item in reset.toasts} == {item.key for item in first.toasts}
    muted = advance(reset, replace(state, communications=replace(feed, muted_apps=("owned",))), 5000)
    assert not muted.toasts


def test_small_viewport_pages_through_every_pending_item_even_when_questions_overflow() -> None:
    feed = Feed(
        updates=tuple(
            Update(WindowsNotice(NoticeKey(index, index + 10), "owned"), f"Item {index}", "Fixture", "Mail", index) for index in range(1, 8)
        )
    )
    requests = tuple(request(Provider.CLAUDE, event(Provider.CLAUDE, str(index)), str(index), index) for index in range(8, 12))
    state = Session(identity="one", communications=feed, console_requests=requests)
    for limit in (1, 2, 3):
        stack = advance(Stack(), state, 100, limit=limit)
        seen = {toast.key for toast in stack.toasts}
        for page in range(1, stack.pages):
            stack = advance(stack, state, 100, page=page, reveal=True, limit=limit)
            assert len(stack.toasts) <= limit
            seen.update(toast.key for toast in stack.toasts)
        assert seen == {item.key for item in observed(state)}


def test_expanded_question_context_excludes_other_topics_in_the_same_chat() -> None:
    feed = Feed(
        conversations=(Conversation("chat", "Project"),),
        followed=("chat",),
        messages=(
            Message("chat", "budget", "Anna", "Can you approve the budget?", 1, 1),
            Message("chat", "lunch", "Sam", "Lunch is in the kitchen.", 2, 2),
        ),
    )
    candidates = collect(feed, ())
    assert len(candidates) == 2
    source = next(item for item in candidates if "budget" in item.body)
    proposal = Assessment(
        "budget",
        ((source.identity, source.revision),),
        "Review the budget request",
        "Anna asks for approval.",
        "Check the figures before deciding.",
        "",
        1,
        1,
    )
    row = observed(Session(communications=feed, triage=Board(enabled=True, items=(proposal,))))[0]
    context = "".join(span.text for span in expanded_spans(row))
    assert "Can you approve the budget?" in context and "Lunch" not in context and "kitchen" not in context
    assert "Request" in context and "Suggested approach" in context


def test_multiple_choice_questions_show_options_for_voice_without_submitting_one_choice() -> None:
    # Defect: a pill click prematurely submits one choice from a multi-select request.
    current = request(Provider.CLAUDE, event(Provider.CLAUDE), "multiple", 1)
    current = replace(current, questions=(replace(current.questions[0], multiple=True),))
    row = next(item for item in observed(Session(console_requests=(current,))) if item.key.source == "console")
    assert not action_spans(row)
    assert "Revenue" in "".join(span.text for span in body_spans(row))
