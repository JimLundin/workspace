"""Desktop conversation projection into the canvas and floating attention."""

from dataclasses import replace
from typing import assert_never

import automation.task
import desktop_ui.agent_session
from assistant.canvas_activity import Attention, CanvasActivity, CanvasQuestion, CanvasReply, SessionRequest, question_body
from assistant.feed_origin import FeedRequest


def canvas_reply(reply: desktop_ui.agent_session.RequestReply) -> CanvasReply:
    match reply:
        case desktop_ui.agent_session.Pending():
            return Attention.WAITING
        case desktop_ui.agent_session.Cancelled() | automation.task.ApprovalDecision():
            return Attention.CLOSED
        case automation.task.TextAnswer():
            return reply
        case _:
            assert_never(reply)


def session_activity(session: desktop_ui.agent_session.Snapshot) -> tuple[CanvasActivity, ...]:
    result: tuple[CanvasActivity, ...] = ()
    work_ids: tuple[str, ...] = ()
    for message in session.messages:
        match message:
            case desktop_ui.agent_session.ChatMessage(speaker="You", source=source):
                work_ids = (source.identity,) if source is not None else ()
            case desktop_ui.agent_session.AgentRequest(
                request=automation.task.Question(id=identity, text=title), detail=detail, created_at=at, reply=reply
            ):
                result = (
                    *result,
                    CanvasQuestion(
                        "question:" + identity,
                        title[:240] or "Your input is needed",
                        question_body(title, detail),
                        at,
                        SessionRequest(session.identity, identity),
                        canvas_reply(reply),
                        work_ids,
                    ),
                )
            case _:
                pass
    return result


def settle_session(activity: tuple[CanvasActivity, ...], session: desktop_ui.agent_session.Snapshot) -> tuple[CanvasActivity, ...]:
    live = frozenset(item.request for item in session_activity(session) if isinstance(item, CanvasQuestion))
    return tuple(
        replace(item, reply=Attention.CLOSED)
        if isinstance(item, CanvasQuestion)
        and isinstance(item.request, SessionRequest)
        and item.reply is Attention.WAITING
        and item.request not in live
        else item
        for item in activity
    )


def redirect_session(session: desktop_ui.agent_session.Snapshot) -> desktop_ui.agent_session.Snapshot:
    """The floating surface is navigation and guarded approvals, not app arrivals."""
    messages: tuple[desktop_ui.agent_session.Message, ...] = ()
    for message in session.messages:
        match message:
            case desktop_ui.agent_session.AgentRequest(
                request=automation.task.Question(id=identity, text=title), reply=desktop_ui.agent_session.Pending(), created_at=at
            ):
                target = "question:" + identity
                messages = (
                    *messages,
                    desktop_ui.agent_session.ChatMessage(
                        "Workspace",
                        desktop_ui.agent_session.notice_text("Your input is needed · " + title[:180], target),
                        at,
                        FeedRequest("canvas:" + target, title[:240]),
                    ),
                )
            case desktop_ui.agent_session.AgentRequest(request=automation.task.Approval()):
                messages = (*messages, message)
            case desktop_ui.agent_session.ChatMessage(source=source) if source is not None and source.identity.startswith("canvas:"):
                messages = (*messages, message)
            case _:
                pass
    return replace(session, phase="idle", messages=messages)
