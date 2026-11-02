"""Desktop conversation projection into the canvas and floating attention."""

from dataclasses import replace
from typing import assert_never

import automation.task
import desktop_ui.agent_session
from assistant.canvas_activity import Attention, CanvasActivity, CanvasQuestion, CanvasReply, SessionRequest, question_body


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
