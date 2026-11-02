"""Phase boundaries, transient retention and canvas navigation precedence."""

from dataclasses import replace

from assistant.agent_progress import Progress, advance_progress, visible
from assistant.agent_session import Begin, CanvasNotice, CanvasSettled, ChatMessage, Session, transition
from assistant.notifications import PhaseKey, Turn, body, steps

from assistant.feed_origin import FeedRequest, Initiation
from automation.presentation import Answer, Finished, ReasoningSummary, StreamState, Succeeded, ToolActivity


def test_progress_and_completion_share_one_card_for_the_requested_outcome() -> None:
    # Defect: reasoning/action phases each settle into their own card, leaving
    # a stopped action card alongside the finished answer for the same request.
    session = transition(Session(identity="run"), Begin("Compare plans", 1))
    session = transition(session, ReasoningSummary("read", "Checking the plans", 2))
    session = transition(session, ToolActivity("read", "read_file", "plan.md", 3))
    progress = advance_progress(Progress(), session, 10)
    key = progress.toasts[0].key
    session = transition(session, ReasoningSummary("compare", "Comparing dates", 4))
    session = transition(session, Answer("result", "The newer plan is approved.", 5, StreamState.COMPLETE))
    session = transition(session, Finished())
    progress = advance_progress(progress, session, 11)
    cards = visible(progress, 5).toasts
    assert [toast.key for toast in cards] == [key]
    assert body(cards[0].content) == "The newer plan is approved."


def test_tools_and_public_updates_keep_one_stable_request_card() -> None:
    # Defect: each tool or public update becomes another completion window.
    session = Session(identity="run", phase="running", messages=(ChatMessage("You", "Compare plans", 1),))
    session = transition(session, ReasoningSummary("read", "Checking the plans", 2))
    first = ToolActivity("a", "read_file", "plan.md", 3)
    session = transition(session, first)
    session = transition(session, ToolActivity("b", "read_file", "plan-v2.md", 4))
    progress = advance_progress(Progress(), session, 10)
    assert isinstance(progress.toasts[0].content, Turn)
    assert len(progress.toasts) == 1 and len(steps(progress.toasts[0].content)) == 2
    key = progress.toasts[0].key
    session = transition(session, replace(first, outcome=Succeeded("Read plan")))
    progress = advance_progress(progress, session, 11)
    assert len(progress.toasts) == 1 and progress.toasts[0].key == key
    session = transition(session, ReasoningSummary("compare", "Comparing the versions", 5))
    progress = advance_progress(progress, session, 12)
    assert len(progress.toasts) == 1 and progress.toasts[0].key == key
    session = transition(session, ReasoningSummary("compare", "Comparing the versions and their dates", 5))
    progress = advance_progress(progress, session, 13)
    assert len(progress.toasts) == 1 and progress.toasts[-1].key == key
    assert body(progress.toasts[-1].content) == "Comparing the versions and their dates"


def test_progress_is_bounded_expires_without_replay_and_keeps_canvas_redirects() -> None:
    # Defect: bursts retain unbounded native content, expired steps return on
    # status refresh, or activity displaces a needed canvas redirect.
    session = Session(identity="run", phase="running")
    session = transition(session, CanvasNotice("Existing finding", "note:earlier", 0.5))
    progress = Progress()
    for index in range(8):
        session = transition(session, Begin("Find document " + str(index), index + 1))
        session = transition(session, Answer(str(index), "Found a document " + str(index), index + 1, StreamState.COMPLETE))
        session = transition(session, Finished())
        progress = advance_progress(progress, session, index + 10)
        assert len(progress.toasts) <= 3
    session = transition(session, CanvasNotice("Choose a version", "question:version", 20))
    progress = advance_progress(progress, session, 20)
    selected = visible(progress, 1)
    assert len(selected.toasts) == 1 and not isinstance(selected.toasts[0].key, PhaseKey)
    assert "Open on canvas" in body(selected.toasts[0].content)
    session = transition(session, Finished())
    progress = advance_progress(progress, session, 21)
    progress = advance_progress(progress, session, 100)
    assert not progress.toasts
    assert not advance_progress(progress, session, 200).toasts
    session = transition(session, CanvasSettled(frozenset(("note:earlier",))))
    assert not advance_progress(progress, session, 201).toasts


def test_first_tool_is_visible_without_a_preceding_public_update() -> None:
    # Defect: a resumed worker emits tools before any public update, leaving
    # its activity invisible or without a stable identity for subsequent calls.
    session = Session(identity="resumed", phase="running")
    session = transition(session, ToolActivity("read", "read_file", "plan.md", 2))
    progress = advance_progress(Progress(), session, 10)
    session = transition(session, ToolActivity("compare", "read_file", "plan-v2.md", 3))
    progress = advance_progress(progress, session, 11)
    assert len(progress.toasts) == 1 and progress.toasts[0].key == PhaseKey("request:0")
    content = progress.toasts[0].content
    assert isinstance(content, Turn) and len(steps(content)) == 2


def test_automatic_investigation_stays_quiet_but_its_question_can_interrupt() -> None:
    # Defect: automatically received FYI produces progress/completion cards,
    # or quieting investigation also hides a question requiring user attention.
    source = FeedRequest("chat:notice", "Routine update", initiation=Initiation.AUTOMATIC)
    session = transition(Session(identity="automatic"), Begin("Routine update", 1, source=source))
    session = transition(session, ReasoningSummary("review", "Checking relevance", 2))
    session = transition(session, ToolActivity("read", "read_file", "project.md", 3))
    progress = advance_progress(Progress(), session, 10)
    assert not visible(progress, 5).toasts
    session = transition(session, CanvasNotice("Which deadline applies?", "question:deadline", 4))
    progress = advance_progress(progress, session, 11)
    assert len(visible(progress, 5).toasts) == 1 and not progress.toasts
    session = transition(session, CanvasSettled(frozenset(("question:deadline",))))
    session = transition(session, Answer("result", "No action is needed.", 5, StreamState.COMPLETE))
    session = transition(session, Finished())
    assert not visible(advance_progress(progress, session, 12), 5).toasts
