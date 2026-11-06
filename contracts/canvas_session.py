"""Desktop conversation projection into the canvas and floating attention."""

from dataclasses import replace
from typing import assert_never

import contracts.agent_session
import contracts.presentation
import contracts.task
from contracts.canvas_activity import Attention, CanvasActivity, CanvasQuestion, CanvasReply, CanvasUpdate, SessionRequest, question_body
from contracts.feed_origin import Initiation


def canvas_reply(reply: contracts.agent_session.RequestReply) -> CanvasReply:
    match reply:
        case contracts.agent_session.Pending():
            return Attention.WAITING
        case contracts.agent_session.Cancelled():
            return Attention.CLOSED
        case contracts.task.TextAnswer():
            return reply
        case _:
            assert_never(reply)


def session_activity(session: contracts.agent_session.Snapshot) -> tuple[CanvasActivity, ...]:
    result: tuple[CanvasActivity, ...] = ()
    work_ids: tuple[str, ...] = ()
    for message in session.messages:
        match message:
            case contracts.agent_session.ChatMessage(speaker="You", source=source):
                work_ids = (source.identity,) if source is not None else ()
            case contracts.agent_session.AgentRequest(
                request=contracts.task.Question(id=identity, text=title), detail=detail, created_at=at, reply=reply
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
    return (*result, *session_replies(session))


def session_replies(session: contracts.agent_session.Snapshot) -> tuple[CanvasUpdate, ...]:
    """Each finished conversation turn's final reply, which the canvas keeps readable in full.

    A turn finishes when the next request begins or the session goes idle. Quiet
    automatic investigations and canvas announcements are not replies.
    """
    request: contracts.agent_session.ChatMessage | None = None
    replies: tuple[CanvasUpdate, ...] = ()
    for message in session.messages:
        match message:
            case contracts.agent_session.ChatMessage(speaker="You", source=source):
                request = None if source is not None and source.initiation is Initiation.AUTOMATIC else message
            case (
                contracts.agent_session.ChatMessage(speaker="Workspace" | "Error", source=None, text=text, created_at=at)
                | contracts.presentation.Answer(
                    text=text, created_at=at, state=contracts.presentation.StreamState.COMPLETE | contracts.presentation.StreamState.INTERRUPTED
                )
            ) if request is not None and text.strip():
                work_ids = (request.source.identity,) if request.source is not None else ()
                reply = CanvasUpdate(reply_id(session, request), request.text[:240] or "Workspace", text.strip()[:32000], at, work_ids)
                replies = (*(each for each in replies if each.id != reply.id), reply)
            case _:
                pass
    running = reply_id(session, request) if session.busy and request is not None else None
    return tuple(reply for reply in replies if reply.id != running)


def reply_id(session: contracts.agent_session.Snapshot, request: contracts.agent_session.ChatMessage) -> str:
    return f"reply:{session.identity}:{request.created_at}"


def settle_session(activity: tuple[CanvasActivity, ...], session: contracts.agent_session.Snapshot) -> tuple[CanvasActivity, ...]:
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
