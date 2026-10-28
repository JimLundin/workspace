"""The bell counts actionable inbox entries rather than visible or historical bubbles."""

from collections import deque
from collections.abc import Callable
from dataclasses import replace

from assistant.agent_session import Answered, Approval, ChatMessage, Question, Session, Snapshot
from assistant.agent_window import AgentWindow
from assistant.communications import Acknowledgement, Conversation, Delivery, Feed, Message, Reply, Update, WindowsNotice, handle, update_fingerprint
from assistant.console_requests import Provider, Request, State
from assistant.console_requests import Question as ConsoleQuestion
from assistant.feed_triage import Assessment, Board, Disposition
from assistant.inbox_attention import pending_count
from assistant.system_notices import NoticeKey

from .test_agent_window import RecordingView


def test_attention_counts_grouped_chats_unhandled_updates_and_unanswered_prompts() -> None:
    update = Update(WindowsNotice(NoticeKey(1, 2), 'mail'), 'Review', 'Check the budget', 'Outlook', 1)
    muted = replace(update, source=WindowsNotice(NoticeKey(3, 4), 'muted'))
    feed = Feed(conversations=(Conversation('chat', 'Planning'),), followed=('chat',), muted_apps=('muted',),
                messages=(Message('chat', 'one', 'Anna', 'First question', 1, 1),
                          Message('chat', 'two', 'Anna', 'Second question', 2, 2),
                          Message('other', 'three', 'Sam', 'Unfollowed', 3, 3),
                          Message('chat', 'four', 'Me', 'My reply', 4, 4, own=True)),
                updates=(update, muted),
                replies=(Reply('failed', 'chat', 'Planning', 'Draft', 5, Delivery.FAILED),
                         Reply('sent', 'chat', 'Planning', 'Sent', 6, Delivery.OBSERVED)))
    waiting = Request('console', Provider.CODEX, 'session', 'C:/fictional', 'Choose a sheet', '', (ConsoleQuestion('Which sheet?'),), 7)
    session = Session(communications=feed, console_requests=(waiting, replace(waiting, identity='old', state=State.EXPIRED)),
                      messages=(Question('question', 'Which sheet?', '', 8), Approval('approval', 'Approve?', '', 9),
                                Question('answered', 'Old question', '', 1, Answered('Done')),
                                ChatMessage('Workspace', 'A previous answer', 2)))
    assert pending_count(session) == 6  # One chat, update, failed reply, console request, question and approval.
    assert pending_count(replace(session, communications=handle(feed, (Acknowledgement(update.key, update_fingerprint(update)),)))) == 5
    assert pending_count(Session()) == 0


def test_curated_attention_uses_groups_and_ignores_dismissed_work_and_raw_duplicates() -> None:
    updates = tuple(Update(WindowsNotice(NoticeKey(index, index + 10), 'mail'), 'Review', 'Budget', 'Outlook', index)
                    for index in range(1, 8))
    grouped = Assessment('group', (('one', 'revision'), ('two', 'revision')), 'Review budget', '', '', '', 1, 1)
    dismissed = replace(grouped, identity='dismissed', disposition=Disposition.DISMISSED)
    waiting = Request('console', Provider.CLAUDE, 'session', 'C:/fictional', 'Choose', '', (ConsoleQuestion('Which sheet?'),), 2)
    session = Session(communications=Feed(updates=updates), console_requests=(waiting,),
                      triage=Board(enabled=True, items=(grouped, dismissed)))
    assert pending_count(session) == 2
    assert pending_count(replace(session, triage=replace(session.triage, items=(dismissed,)),
                                 console_requests=(replace(waiting, state=State.ANSWERED),))) == 0


def test_attention_snapshots_are_published_on_the_ui_queue_and_stop_after_close() -> None:
    # This fixture owns the event-loop FIFO: callbacks enqueue work while it drains.
    jobs: deque[Callable[[], None]] = deque()
    counts: tuple[int, ...] = ()
    view = RecordingView()
    def publish(state: Snapshot) -> None:
        nonlocal counts
        counts = (*counts, pending_count(state))
    panel = AgentWindow(lambda: None, post=jobs.append, create_view=lambda _: view, on_snapshot=publish)
    try:
        while jobs:
            jobs.popleft()()
        assert counts == (0,)
        panel.request_input(Question('owned', 'Which sheet?', '', 1), lambda _: True)
        assert counts == (0,)
        while jobs:
            jobs.popleft()()
        assert counts == (0, 1)
        assert panel.respond('owned', 'Revenue')
        while jobs:
            jobs.popleft()()
        assert counts == (0, 1, 0)
        panel.request_input(Question('late', 'Another sheet?', '', 2), lambda _: True)
    finally:
        panel.close()
        while jobs:
            jobs.popleft()()
    assert counts == (0, 1, 0)
