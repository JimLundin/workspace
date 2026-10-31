"""Feed dates must reach the agent, and changing days must invalidate old recommendations."""

import json
import threading
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from assistant.communications import Feed, SourceDate, SourceDateStatus, TeamsActivity, Update
from assistant.communications_browser import activity_observation, observation
from assistant.feed_contracts import Disposition
from assistant.feed_sources import Candidate, Excerpt, triage_evidence
from assistant.feed_triage import Board, decode, restored, saved, unassessed
from assistant.feed_triage_service import classify, source_evidence
from assistant.llm import Settings
from assistant.web_apps import TeamsPage, TeamsPost
from tests import fake_endpoint
from tests.feed_fixture import TriageFixture
from tests.feed_source_fixture import captured
from tests.test_feed_triage import output
from tests.test_feed_triage_service import MemoryStore, wait_until
lazy from tests.test_agent import says

LAST_WEEK = datetime(2026, 10, 20, 9, tzinfo=UTC).timestamp()
THIS_WEEK = datetime(2026, 10, 27, 9, tzinfo=UTC).timestamp()


def test_saved_review_dates_refresh_only_open_work_and_only_on_a_new_day() -> None:
    """Lost review stamps cause repeat startup queries; age must not undo handling."""
    reviewed_on = datetime.fromtimestamp(LAST_WEEK, UTC).date()
    today = datetime.fromtimestamp(THIS_WEEK, UTC).date()
    sources = tuple(captured(kind.value, Excerpt("Review", "Please review.", LAST_WEEK)) for kind in Disposition)
    proposals = tuple(
        replace(decode(output(([source.identity], "action")), (source,))[0], disposition=kind, reviewed_on=reviewed_on)
        for source, kind in zip(sources, Disposition, strict=True)
    )
    board = restored(saved(Board(enabled=True, items=proposals)))
    assert not unassessed(board, sources, today=reviewed_on), "Restart must retain the same-day review."
    assert unassessed(board, sources, today=today) == sources[:2], "Automatic assessments need a new review; explicit handling remains."
    unstamped = replace(board, items=(replace(proposals[0], reviewed_on=None), *proposals[1:]))
    assert unassessed(unstamped, sources, today=reviewed_on) == (sources[0],), "Unstamped recommendations need dated review."


def test_corrected_provider_dates_invalidate_open_work_without_reopening_handled_items(tmp_path: Path) -> None:
    """Ignoring date-only provider corrections leaves stale recommendations cached."""
    triage = TriageFixture(MemoryStore(), lambda _batch, _rules: "{}")
    try:
        triage.closed.set()
        updates = tuple(Update(TeamsActivity(str(index)), "Review", "Please review.", "Teams", THIS_WEEK) for index, _kind in enumerate(Disposition))
        triage.observe(Feed(updates=updates))
        before = triage.candidates
        proposals = tuple(
            replace(decode(output(([source.identity], "action")), (source,))[0], disposition=kind)
            for source, kind in zip(before, Disposition, strict=True)
        )
        triage.board = Board(enabled=True, items=proposals)
        corrected = tuple(replace(item, source_time=SourceDate(LAST_WEEK)) for item in updates)
        triage.observe(Feed(updates=corrected))
        assert triage.board.items == proposals[2:]
        assert triage.board.pending == 2
        assert tuple((item.identity, item.revision) for item in triage.candidates) == tuple((item.identity, item.revision) for item in before)
        assert triage.epoch == 1, "An in-flight result with the old date must be fenced out."
        triage.observe(Feed(updates=corrected))
        assert triage.epoch == 1, "Unchanged dates must not keep invalidating reviews."
    finally:
        triage.close()


def test_an_undated_chat_is_not_presented_as_created_today() -> None:
    """The chat adapter must not substitute collection time for missing evidence."""
    page = TeamsPage("19:one@thread.v2", "Review", (), (TeamsPost("one", "Anna", "Tomorrow.", 0, (), own=False),), editor_ready=True)
    found = observation(page, THIS_WEEK)
    feed = Feed(messages=found.messages, followed=(found.current,))
    (source,) = triage_evidence(feed)
    assert source.source_time is SourceDateStatus.UNKNOWN
    assert source_evidence(source).created_at is None


def test_triage_model_receives_readable_current_and_source_dates() -> None:
    source = captured("old-invite", Excerpt("Meeting reminder", "The meeting is tomorrow.", LAST_WEEK))
    with fake_endpoint.fake_endpoint() as endpoint:
        endpoint.replies = [says('{"items": []}')]
        settings = Settings(endpoint.url, "fixture", "transcribe", "chat", "agent", "", "")
        classify(settings, (source,), (), clock=lambda: THIS_WEEK)
        request: object = json.loads(endpoint.last.body)
    match request:
        case {"input": [{"role": "user", "content": str() as content}]}:
            payload: object = json.loads(content)
        case _:
            raise AssertionError("The model request lost its source payload.")
    match payload:
        case {"reviewed_at": str() as reviewed, "candidates": [{"created_at": str() as created}]}:
            assert reviewed.startswith("2026-10-27T")
            assert created == "2026-10-20T09:00:00+00:00"
        case _:
            raise AssertionError("The model needs readable current and source calendar dates, rather than epoch numbers.")


def test_voice_feed_snapshot_keeps_the_source_date_with_its_text(tmp_path: Path) -> None:
    triage = TriageFixture(MemoryStore(), lambda _batch, _rules: "{}", clock=lambda: THIS_WEEK)
    try:
        source = captured("old-invite", Excerpt("Meeting reminder", "The meeting is tomorrow.", LAST_WEEK))
        triage.candidates = (source,)
        snapshot = triage.snapshot()
        assert snapshot.reviewed_at.startswith("2026-10-27T")
        assert snapshot.sources[0].created_at == "2026-10-20T09:00:00+00:00"
    finally:
        triage.close()


def test_teams_activity_uses_the_provider_date_instead_of_its_collection_time() -> None:
    observed = activity_observation(
        {
            "ready": True,
            "items": [
                {
                    "identity": "123",
                    "title": "Meeting reminder",
                    "text": "The meeting is tomorrow.",
                    "kind": "invitation",
                    "created_at": LAST_WEEK,
                    "date_hint": "20 October 2026",
                }
            ],
        },
        THIS_WEEK,
    )
    sources = triage_evidence(Feed(updates=observed.items))
    with fake_endpoint.fake_endpoint() as endpoint:
        endpoint.replies = [says('{"items": []}')]
        classify(Settings(endpoint.url, "fixture", "transcribe", "chat", "agent", "", ""), sources, (), clock=lambda: THIS_WEEK)
        request: object = json.loads(endpoint.last.body)
    match request:
        case {"input": [{"role": "user", "content": str() as content}]}:
            payload: object = json.loads(content)
        case _:
            raise AssertionError("The activity source was not passed to the model.")
    match payload:
        case {"candidates": [{"created_at": "2026-10-20T09:00:00+00:00"}]}:
            pass
        case _:
            raise AssertionError("An old Teams activity was incorrectly stamped as collected today.")


def test_a_new_day_reconsiders_cached_work_without_a_new_notification(tmp_path: Path) -> None:
    now = LAST_WEEK
    calls: list[tuple[str, ...]] = []
    reconsidered = threading.Event()

    def model(batch: tuple[Candidate, ...], rules: tuple[str, ...]) -> str:
        calls.append(tuple(item.identity for item in batch))
        if len(calls) == 2:
            reconsidered.set()
        return output(([item.identity for item in batch], "action" if len(calls) == 1 else "quiet"))

    triage = TriageFixture(MemoryStore(), model, clock=lambda: now)
    try:
        feed = Feed(updates=(Update(TeamsActivity("old-invite"), "Meeting reminder", "The meeting is tomorrow.", "Teams", LAST_WEEK),))
        triage.observe(feed)
        triage.advance()
        wait_until(lambda: bool(triage.board.actions))
        now = THIS_WEEK
        triage.advance()
        assert reconsidered.wait(5), "Last week's recommendation stayed cached despite the current date changing."
        wait_until(lambda: not triage.board.actions)
        assert len(calls) == 2 and calls[0] == calls[1], "Refresh must reconsider the same evidence once, without a new arrival."
    finally:
        triage.close()
