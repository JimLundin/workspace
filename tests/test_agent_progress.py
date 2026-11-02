"""Phase boundaries, transient retention and canvas navigation precedence."""

from dataclasses import replace

from assistant.agent_session import AgentRequest, Begin, CanvasAttention, CanvasNotice, ChatMessage, Resolution, Session, transition
from assistant.attention import observed_attention
from assistant.canvas_activity import Attention, CanvasQuestion, CanvasUpdate, TaskRequest
from assistant.feed_origin import FeedRequest, Initiation
from assistant.work_canvas_model import CanvasCollection, CanvasDocument
from automation.personal_work import Association, Catalog, WorkDefinition, WorkThread
from automation.presentation import Answer, Finished, ReasoningSummary, StreamState, Succeeded, ToolActivity
from automation.task import TextAnswer
from desktop_ui.agent_progress import Progress, advance_progress, phases, visible
from desktop_ui.notifications import Entry, Expires, PhaseKey, Response, Turn, body, steps
from tests.agent_requests import asked


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


def test_completed_cards_expire_in_their_stack_order_despite_different_reading_times() -> None:
    # Defect: an older long result remains above a newer short result that expires first.
    session = Session(
        identity="ordered",
        messages=(
            ChatMessage("You", "First task", 1),
            ChatMessage("Workspace", "Detailed result " * 60, 2),
            ChatMessage("You", "Second task", 3),
            ChatMessage("Workspace", "Brief result", 4),
        ),
    )
    progress = advance_progress(Progress(), session, 10)
    older, newer = progress.toasts
    assert isinstance(older.lifetime, Expires) and isinstance(newer.lifetime, Expires)
    assert older.lifetime.at < newer.lifetime.at
    after_oldest = advance_progress(progress, session, older.lifetime.at)
    assert tuple(toast.key for toast in after_oldest.toasts) == (newer.key,)


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
    question = CanvasQuestion(
        "question:version", "Choose a version", "Which version should be used?", 20, TaskRequest("version", "version"), Attention.WAITING
    )
    session = transition(session, CanvasAttention(observed_attention(Catalog(), CanvasDocument(activity=(question,)))))
    progress = advance_progress(progress, session, 20)
    selected = visible(progress, 1)
    assert len(selected.toasts) == 1 and selected.toasts[0].key == PhaseKey("context:question:version")
    assert "Open on canvas" in body(selected.toasts[0].content)
    session = transition(session, Finished())
    session = transition(
        session, CanvasAttention(observed_attention(Catalog(), CanvasDocument(activity=(replace(question, reply=Attention.CLOSED),))))
    )
    progress = advance_progress(progress, session, 21)
    progress = advance_progress(progress, session, 100)
    assert not progress.toasts
    assert not advance_progress(progress, session, 200).toasts
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
    question = CanvasQuestion(
        "question:deadline",
        "Which deadline applies?",
        "The schedule lists Monday and Friday.",
        4,
        TaskRequest("automatic", "deadline"),
        Attention.WAITING,
        (source.identity,),
    )
    session = transition(session, CanvasAttention(observed_attention(Catalog(), CanvasDocument(activity=(question,)))))
    session = transition(session, CanvasNotice("Which deadline applies?", "question:deadline", 4))
    progress = advance_progress(progress, session, 11)
    assert len(visible(progress, 5).toasts) == 1 and "Monday and Friday" in body(progress.toasts[0].content)
    session = transition(
        session, CanvasAttention(observed_attention(Catalog(), CanvasDocument(activity=(replace(question, reply=TextAnswer("Monday")),))))
    )
    session = transition(session, Answer("result", "No action is needed.", 5, StreamState.COMPLETE))
    session = transition(session, Finished())
    progress = advance_progress(progress, session, 12)
    assert len(progress.toasts) == 1 and "No action is needed" not in body(progress.toasts[0].content)
    assert not visible(advance_progress(progress, session, 100), 5).toasts


def test_related_canvas_question_and_result_keep_the_original_request_card() -> None:
    # Defect: different canvas contribution ids create separate desktop cards,
    # or the result displaces a pending question's complete request and route.
    work = WorkThread("work:budget", 0, WorkDefinition("Budget", "Review budget"), (), 1, 1)
    catalog = Catalog(works=(work,))
    question = CanvasQuestion(
        "question:budget", "Which budget?", "Choose approved or forecast figures.", 3, TaskRequest("review", "budget"), Attention.WAITING, (work.id,)
    )
    session = transition(Session(identity="review"), Begin("Review budget", 1, source=FeedRequest(work.id, "Budget")))
    progress = advance_progress(Progress(), session, 10)
    key = progress.toasts[0].key
    session = transition(session, CanvasAttention(observed_attention(catalog, CanvasDocument(activity=(question,)))))
    session = transition(session, CanvasNotice(question.title, question.id, 3))
    progress = advance_progress(progress, session, 11)
    assert [toast.key for toast in progress.toasts] == [key]
    assert "approved or forecast" in body(progress.toasts[0].content)
    assert progress.observed[0].request == question.request
    result = CanvasUpdate("result:review", "Budget checked", "Approved totals match.", 5, (work.id,))
    answered = replace(question, reply=TextAnswer("Approved"))
    session = transition(session, Finished())
    session = transition(session, CanvasAttention(observed_attention(catalog, CanvasDocument(activity=(answered, result)))))
    session = transition(session, CanvasNotice(result.title, result.id, 5))
    progress = advance_progress(progress, session, 12)
    assert [toast.key for toast in progress.toasts] == [key]
    assert "Approved totals match" in body(progress.toasts[0].content)
    assert (
        len(
            [
                message
                for message in session.messages
                if isinstance(message, ChatMessage) and message.source is not None and message.source.identity.startswith("canvas:")
            ]
        )
        == 1
    )


def test_two_replies_in_one_context_remain_attached_to_their_own_questions() -> None:
    # Defect: coalescing independently indexed turns drops a reply or attaches
    # it to another question when the desktop card combines their work context.
    source = FeedRequest("work:budget", "Budget")
    session = transition(Session(identity="review"), Begin("Check budget", 1, source=source))
    session = transition(session, asked("figures", "Which figures?", "Approved or forecast", 2))
    session = transition(session, Resolution("figures", TextAnswer("Approved")))
    session = transition(session, Begin("Continue budget", 3, source=source))
    session = transition(session, asked("deadline", "When is it due?", "Monday or Friday", 4))
    session = transition(session, Resolution("deadline", TextAnswer("Monday")))
    cards = tuple(phases(session))
    assert len(cards) == 1
    entries = cards[0].turn.entries
    replies = {
        entry.message.id: response.text
        for entry in entries
        if isinstance(entry, Entry) and isinstance(entry.message, AgentRequest)
        for response in entries
        if isinstance(response, Response) and response.index == entry.index
    }
    assert replies == {"figures": "Approved", "deadline": "Monday"}


def test_new_work_connection_keeps_the_existing_card_despite_canvas_arrangement() -> None:
    # Defect: connecting a reviewed source to work replaces its live card, or
    # moving related contributions into different canvas groups splits it again.
    source = FeedRequest("source:budget", "Budget notice")
    session = transition(Session(identity="review"), Begin("Review budget", 1, source=source))
    progress = advance_progress(Progress(), session, 10)
    key = progress.toasts[0].key
    work = WorkThread("work:budget", 0, WorkDefinition("Budget", "Review budget"), (Association(source.identity, "Budget evidence"),), 1, 1)
    question = CanvasQuestion(
        "question:budget", "Which budget?", "Approved or forecast?", 2, TaskRequest("review", "budget"), Attention.WAITING, (work.id,)
    )
    result = CanvasUpdate("result:budget", "Review prepared", "Both versions are available.", 3, (work.id,))
    document = CanvasDocument(
        activity=(question, result),
        collections=(CanvasCollection("group:questions", "Questions", (question.id,)), CanvasCollection("group:results", "Results", (result.id,))),
    )
    session = transition(session, CanvasAttention(observed_attention(Catalog(works=(work,)), document)))
    session = transition(session, CanvasNotice(question.title, question.id, 2))
    session = transition(session, CanvasNotice(result.title, result.id, 3))
    progress = advance_progress(progress, session, 11)
    assert [toast.key for toast in progress.toasts] == [key]
    assert progress.observed[0].request == question.request
    assert "Approved or forecast" in body(progress.toasts[0].content) and "Both versions are available" in body(progress.toasts[0].content)
