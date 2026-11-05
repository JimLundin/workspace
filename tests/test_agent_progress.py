"""Phase boundaries by work context, and what the bar reads from them: requests, steps and news."""

from dataclasses import replace

from assistant.agent_session import AgentRequest, Begin, CanvasAttention, CanvasNotice, Resolution, Session, transition
from assistant.attention import observed_attention
from assistant.canvas_activity import Attention, CanvasQuestion, CanvasUpdate, TaskRequest
from assistant.feed_origin import FeedRequest, Initiation
from assistant.work_canvas_model import CanvasCollection, CanvasDocument
from automation.personal_work import Association, Catalog, WorkDefinition, WorkThread
from automation.presentation import Answer, Finished, ReasoningSummary, StreamState, Succeeded, ToolActivity
from automation.task import TextAnswer
from desktop_ui.agent_progress import Entry, Response, phases, stable_phases
from desktop_ui.island_agent import activity, notices
from desktop_ui.island_model import Agent
from desktop_ui.island_moment import Notice
from desktop_ui.request_panel import Request, request
from tests.agent_requests import asked


def test_progress_and_completion_share_one_phase_and_the_finished_reply_is_news() -> None:
    # Defects: reasoning and actions split one requested outcome into several
    # phases, the reply is announced while work still runs, or not at all.
    session = transition(Session(identity="run"), Begin("Compare plans", 1))
    session = transition(session, ReasoningSummary("read", "Checking the plans", 2))
    session = transition(session, ToolActivity("read", "read_file", "plan.md", 3, Succeeded("Read")))
    session = transition(session, ReasoningSummary("compare", "**Comparing dates**", 4))
    session = transition(session, Answer("result", "The **newer** plan is approved.", 5, StreamState.COMPLETE))
    assert len(tuple(phases(session))) == 1
    assert notices(session) == ()
    assert activity(session) == Agent("The newer plan is approved.", waiting=False, steps=("Checking the plans", "Read file", "Comparing dates"))
    session = transition(session, Finished())
    assert len(tuple(phases(session))) == 1
    assert notices(session) == (Notice("reply:run:1", "Compare plans", "The newer plan is approved.", "reply:run:1", 5),)


def test_automatic_investigation_stays_quiet_but_its_question_is_news() -> None:
    # Defects: an automatically received FYI announces its progress and reply,
    # or quieting the investigation also hides a question that needs the person.
    source = FeedRequest("chat:notice", "Routine update", initiation=Initiation.AUTOMATIC)
    session = transition(Session(identity="automatic"), Begin("Routine update", 1, source=source))
    session = transition(session, ToolActivity("read", "read_file", "project.md", 3))
    session = transition(session, Answer("result", "No action is needed.", 4, StreamState.COMPLETE))
    session = transition(session, Finished())
    assert (tuple(phases(session)), notices(session)) == ((), ())
    question = CanvasQuestion(
        "question:deadline",
        "Which deadline applies?",
        "The schedule lists Monday and Friday.",
        5,
        TaskRequest("automatic", "deadline"),
        Attention.WAITING,
        (source.identity,),
    )
    session = transition(session, CanvasAttention(observed_attention(Catalog(), CanvasDocument(activity=(question,)))))
    session = transition(session, CanvasNotice("Which deadline applies?", "question:deadline", 6))
    (phase,) = phases(session)
    assert request(phase) == Request(
        "Which deadline applies?", "The schedule lists Monday and Friday.", "question:deadline", "N toggles a spoken reply"
    )
    assert notices(session) == (
        Notice(
            "canvas:question:deadline:6",
            "Which deadline applies?",
            "The schedule lists Monday and Friday.",
            "question:deadline",
            6,
            question=True,
        ),
    )


def test_related_canvas_question_and_result_keep_the_original_request_phase() -> None:
    # Defects: different canvas contribution ids create separate phases, or the
    # result displaces a pending question's complete request and route.
    work = WorkThread("work:budget", 0, WorkDefinition("Budget", "Review budget"), (), 1, 1)
    catalog = Catalog(works=(work,))
    question = CanvasQuestion(
        "question:budget", "Which budget?", "Choose approved or forecast figures.", 3, TaskRequest("review", "budget"), Attention.WAITING, (work.id,)
    )
    session = transition(Session(identity="review"), Begin("Review budget", 1, source=FeedRequest(work.id, "Budget")))
    (before,) = phases(session)
    session = transition(session, CanvasAttention(observed_attention(catalog, CanvasDocument(activity=(question,)))))
    session = transition(session, CanvasNotice(question.title, question.id, 3))
    (asking,) = phases(session)
    assert asking.key == before.key and asking.request == question.request
    assert request(asking).detail == "Choose approved or forecast figures."
    result = CanvasUpdate("result:review", "Budget checked", "Approved totals match.", 5, (work.id,))
    answered = replace(question, reply=TextAnswer("Approved"))
    session = transition(session, Finished())
    session = transition(session, CanvasAttention(observed_attention(catalog, CanvasDocument(activity=(answered, result)))))
    session = transition(session, CanvasNotice(result.title, result.id, 5))
    (finished,) = phases(session)
    assert finished.key == before.key
    assert notices(session)[-1] == Notice("canvas:result:review:5", "Budget checked", "Approved totals match.", "result:review", 5)


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


def test_new_work_connection_keeps_the_existing_phase_despite_canvas_arrangement() -> None:
    # Defect: connecting a reviewed source to work replaces the open request's
    # phase, or moving related contributions into different canvas groups splits it.
    source = FeedRequest("source:budget", "Budget notice")
    session = transition(Session(identity="review"), Begin("Review budget", 1, source=source))
    previous = tuple(phases(session))
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
    (kept,) = stable_phases(phases(session), previous)
    assert kept.key == previous[0].key and kept.request == question.request
    assert request(kept).detail == "Approved or forecast?"
