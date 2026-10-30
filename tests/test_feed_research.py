"""Background research wiring through real SDK calls, stores, files and source history."""

import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date
from pathlib import Path
from unittest import TestCase

from pydantic import TypeAdapter

from assistant.activity import ContextSnapshot
from assistant.communications import Conversation, Feed, Message, acknowledge
from assistant.feed_contracts import DismissItem, Disposition, StoredBoard
from assistant.feed_research import Research
from assistant.feed_sources import triage_evidence
from assistant.feed_triage import Board, decode, proposal_revision, restored, saved, unassessed
from assistant.feed_triage_service import classify
from assistant.feed_work import FeedWork
from assistant.llm import Json, Settings
from automation.context import ContextStore, ProjectNote
from automation.store import TaskStore
from tests.fake_endpoint import Received, Reply, fake_endpoint
from tests.feed_fixture import TriageFixture
from tests.test_feed_triage import output
from tests.test_feed_triage_service import MemoryStore
lazy from tests.test_agent import calls, says

_OBJECT = TypeAdapter(dict[str, Json])


def test_background_research_reads_topic_memory_full_thread_and_file_before_publishing(tmp_path: Path) -> None:
    # Defect: the reviewer cannot retrieve sources, drops observations between
    # tool turns, uses quick chat, or exposes write/desktop/approval tools.
    path = tmp_path / "atlas.txt"
    path.write_text("The approved Atlas budget is 100; the current forecast is 112.", encoding="utf-8")
    tasks = TaskStore(tmp_path / "work.sqlite3")
    memory = ContextStore(tasks.path)
    memory.save(ProjectNote("atlas", "Atlas", "Use the approved budget, not last month's estimate.", str(path), 10, 100))
    feed = Feed(
        followed=("atlas",),
        conversations=(Conversation("atlas", "Atlas forecast"), Conversation("orion", "Orion")),
        messages=(
            Message("atlas", "old", "Alice", "Last month's estimate was 90.", 10, 10),
            Message("atlas", "answer", "Jim", "Use the approved budget of 100.", 11, 11, own=True),
            Message("atlas", "new", "Alice", "Explain the variance in " + str(path), 12, 12),
            Message("orion", "private", "Bob", "Unrelated confidential discussion.", 12, 12),
        ),
    )
    feed = acknowledge(acknowledge(feed, feed.messages[0].key), feed.messages[3].key)
    batch = triage_evidence(feed)
    assert len(batch) == 1
    triage = TriageFixture(
        MemoryStore(),
        lambda _batch, _rules: "{}",
        work=FeedWork(tasks, memory, lambda: ContextSnapshot(50, "active", ())),
        clock=lambda: 50,
    )
    try:
        triage.observe(feed)
        with fake_endpoint() as endpoint:
            endpoint.replies = [
                calls(
                    ("lookup_work", {"query": "Atlas"}), ("read_conversation", {"source_id": batch[0].identity}), ("read_file", {"path": str(path)})
                ),
                calls(("write_file", {"path": str(path), "text": "modified"})),
                says(output(([batch[0].identity], "action"))),
            ]
            settings = Settings(endpoint.url, "fixture", "transcribe", "quick", "agent", "", "", agent_reasoning_effort="high")
            research = Research(settings, triage.research_context, triage.research_conversation, stop=triage.closed)
            review = classify(settings, batch, (), research=research, clock=lambda: 50)
            requests = tuple(_OBJECT.validate_json(item.body) for item in endpoint.received)
        assert len(decode(review, batch)) == 1 and len(requests) == 3
        for request in requests:
            assert request["model"] == "agent" and request["reasoning"] == {"effort": "high", "summary": "auto"}
            assert request["store"] is False
        match requests[0]["tools"]:
            case list() as tools:
                names = frozenset(name for tool in tools if isinstance(tool, dict) and isinstance(name := tool.get("name"), str))
            case _:
                raise AssertionError("Research tools were not offered.")
        assert names == {"lookup_work", "read_conversation", "read_file", "list_directory", "web_search"}
        evidence = _OBJECT.dump_json(requests[1]).decode()
        assert "approved Atlas budget is 100" in evidence and "Last month's estimate was 90" in evidence
        assert "Use the approved budget of 100" in evidence and "Use the approved budget, not last month's estimate" in evidence
        assert "Unrelated confidential discussion" not in evidence
        assert "not found" in _OBJECT.dump_json(requests[2]).decode().lower()
        assert path.read_text(encoding="utf-8") == "The approved Atlas budget is 100; the current forecast is 112."
    finally:
        triage.close()


def test_own_reply_reconsiders_cached_work_and_cannot_be_overwritten_by_old_research(tmp_path: Path) -> None:
    # Defect: a user's reply changes neither pending candidates nor cached
    # review freshness, leaving options based on the unanswered old request.
    feed = Feed(followed=("atlas",), messages=(Message("atlas", "question", "Alice", "Which forecast should I use?", 10, 10),))
    batch = triage_evidence(feed)
    item = decode(output(([batch[0].identity], "action")), batch)[0]
    store = MemoryStore()
    store.data = saved(Board(enabled=True, items=(item,)))
    triage = TriageFixture(store, lambda _batch, _rules: "{}")
    try:
        triage.observe(feed)
        # Simulate a current committed review through the actual immutable board contract.
        day = date(2026, 10, 29)
        triage.board = replace(triage.board, items=(replace(item, reviewed_on=day),))
        epoch = triage.epoch
        answered = replace(feed, messages=(*feed.messages, Message("atlas", "reply", "Jim", "Use the approved forecast.", 11, 11, own=True)))
        triage.observe(answered)
        assert triage_evidence(answered) == batch
        assert triage.epoch == epoch + 1 and unassessed(triage.board, batch, today=day) == batch
        assert "Use the approved forecast" in triage.research_conversation(batch[0].identity)
        triage.edit(DismissItem(item.identity))
        triage.observe(replace(answered, messages=(*answered.messages, Message("atlas", "thanks", "Jim", "Thanks.", 12, 12, own=True))))
        assert not triage.board.actions and not unassessed(triage.board, batch, today=day)
    finally:
        triage.close()


def test_public_research_supplies_findings_or_an_explicit_access_gap_without_losing_local_work() -> None:
    # Defect: private context is included in the public lookup, hosted-tool
    # failure aborts all inbox review, or returned findings never reach the reviewer.
    feed = Feed(followed=("atlas",), messages=(Message("atlas", "one", "Alice", "Private Atlas project details.", 10, 10),))
    batch = triage_evidence(feed)
    findings = "Official documentation describes an export option: https://example.org/docs/export"
    for status in (200, 400):
        with fake_endpoint() as endpoint:
            endpoint.replies = [calls(("web_search", {"query": "documented export options"})), says(output(([batch[0].identity], "action")))]

            def respond(request: Received, status: int = status) -> Reply:
                payload = _OBJECT.validate_json(request.body)
                if payload.get("tools") == [{"type": "web_search"}]:
                    assert payload["input"] == "documented export options"
                    assert "Private Atlas" not in request.body.decode() and payload["store"] is False
                    if status == 400:
                        return Reply(_OBJECT.dump_json({"error": {"message": "Hosted web search is not supported."}}), status=400)
                    return Reply(
                        _OBJECT.dump_json(
                            {
                                "id": "resp_web",
                                "object": "response",
                                "created_at": 1,
                                "model": "agent",
                                "status": "completed",
                                "output": [
                                    {
                                        "id": "msg_web",
                                        "type": "message",
                                        "role": "assistant",
                                        "status": "completed",
                                        "content": [{"type": "output_text", "text": findings, "annotations": []}],
                                    }
                                ],
                            }
                        )
                    )
                return endpoint.replies.pop(0)

            endpoint.respond = respond
            settings = Settings(endpoint.url, "fixture", "transcribe", "quick", "agent", "", "")
            review = classify(settings, batch, ())
            assert len(decode(review, batch)) == 1 and len(endpoint.received) == 3
            evidence = endpoint.last.body.decode()
            assert (findings if status == 200 else "could not complete hosted web research") in evidence


def test_shutdown_cancels_a_pending_model_request_without_waiting_for_network_timeout() -> None:
    # Defect: closing Workspace leaves research/network work alive until the
    # provider timeout, or publishes a recommendation after cancellation.
    entered, release, stop = threading.Event(), threading.Event(), threading.Event()
    with fake_endpoint() as endpoint:
        settings = Settings(endpoint.url, "fixture", "transcribe", "quick", "agent", "", "")
        endpoint.replies = [says('{"items": []}')]
        classify(settings, (), ())

        def stream(_request: object) -> Iterator[bytes]:
            entered.set()
            release.wait(5)
            yield b"data: [DONE]\n\n"

        endpoint.stream = stream
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(classify, settings, (), (), research=Research(settings, stop=stop))
            try:
                assert entered.wait(5)
                stop.set()
                with TestCase().assertRaises(OSError):
                    future.result(timeout=3)
            finally:
                release.set()


def test_old_recipe_refreshes_automatic_options_but_preserves_dismissal() -> None:
    # Defect: the deployed research recipe keeps displaying cached shallow
    # options all day, or uses a recipe refresh to reopen dismissed work.
    from_source = Feed(followed=("atlas",), messages=(Message("atlas", "one", "Alice", "Review Atlas.", 10, 10),))
    batch = triage_evidence(from_source)
    day = date(2026, 10, 29)
    item = replace(decode(output(([batch[0].identity], "action")), batch)[0], reviewed_on=day)
    state = saved(Board(enabled=True, items=(item,)))
    old = StoredBoard(state.rules, state.items, state.history, review_version=2)
    refreshed = restored(old)
    assert unassessed(refreshed, batch, today=day) == batch and proposal_revision(refreshed.actions[0]) == proposal_revision(item)
    dismissed = replace(item, disposition=Disposition.DISMISSED)
    state = saved(Board(enabled=True, items=(dismissed,)))
    old = StoredBoard(state.rules, state.items, state.history, review_version=2)
    assert not unassessed(restored(old), batch, today=day) and not restored(old).actions
