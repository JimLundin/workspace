"""Context and reply ownership through real local stores and the registered feed tools."""

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from unittest import TestCase

from pydantic import TypeAdapter

from assistant.activity import Activity, ContextSnapshot
from assistant.feed_agent_tools import request
from assistant.feed_contracts import REVIEW_INPUT, DismissItem, Disposition, FeedRejected, FeedReply, StoredBoard
from assistant.feed_history import Decision, Handoff
from assistant.feed_sources import Excerpt
from assistant.feed_triage import Board, decode, proposal_revision, restored, saved, unassessed
from assistant.feed_triage_service import classify
from assistant.feed_work import FeedWork
from assistant.llm import Json, Settings
from automation.actions import Resources
from automation.context import ContextStore, Preference, ProjectNote
from automation.execution import WorkExecution
from automation.store import TaskStore
from automation.task import Completed, FeedHandoff, Profile, Question, RequestSource, TextAnswer, Waiting
from tests.fake_endpoint import fake_endpoint
from tests.feed_fixture import TriageFixture, feed_bridge
from tests.feed_source_fixture import captured
from tests.test_feed_triage import output
from tests.test_feed_triage_service import MemoryStore
from tests.test_work_actions import claimed
from winapi.shapes import Window
lazy from tests.test_agent import ToolRig, says

_OBJECT = TypeAdapter(dict[str, Json])


def test_model_gets_project_facts_prior_decisions_task_results_and_recorded_answers(tmp_path: Path) -> None:
    # Defect: reviewing notifications alone, using the quick chat model, or
    # omitting durable answers/results loses the context needed for useful suggestions.
    tasks = TaskStore(tmp_path / "work.sqlite3")
    context = ContextStore(tasks.path)
    context.save(Preference("style", "Reply style", "Explain the tradeoff before recommending.", "Jim", 10))
    context.save(ProjectNote("atlas", "Atlas", "Compare the forecast to the approved baseline.", "atlas/plan", 10, 100))
    context.save(ProjectNote("orion", "Orion", "Unrelated secret project fact.", "orion/plan", 10, 100))
    context.save(ProjectNote("old", "Atlas", "The obsolete total is 900.", "atlas/old", 10, 20))
    tasks.submit("analysis", "Atlas variance", "Compare the Atlas forecast.", RequestSource("feed"), at=10)
    first = tasks.claim("worker", "first", at=11)
    assert first is not None
    tasks.finish(first.run, Waiting(Question("baseline", "Which baseline?", "")), at=12)
    tasks.answer("analysis", "baseline", TextAnswer("Use the approved forecast."), at=13)
    second = tasks.claim("worker", "second", at=14)
    assert second is not None
    detailed_result = "Atlas variance is 12; supplier costs explain it.\n" + "\n".join(
        f"Supplier line {index}: compare the approved forecast with the revised purchase schedule and explain the cost difference."
        for index in range(16)
    )
    tasks.finish(second.run, Completed(detailed_result, ("Read the approved forecast.",)), at=15)
    desktop = ContextSnapshot(50, "active", (Activity(Window(1, "Atlas forecast", "excel.exe", minimized=False), 40, 50, agent_active=False),))
    work = FeedWork(tasks, context, lambda: desktop)
    source = captured("atlas", Excerpt("Atlas forecast", "Explain the variance before Friday.", 40))
    item = decode(output(([source.identity], "action")), (source,))[0]
    decision = Decision(
        "correction",
        "propose",
        item.identity,
        proposal_revision(item),
        item.title,
        item.summary,
        "Atlas: use the approved baseline, not last month's estimate.\n"
        + "\n".join(
            f"For budget line {index}, show the supplier assumption and the approved baseline before recommending a revision." for index in range(16)
        ),
        30,
        Handoff("analysis", "Compare the Atlas forecast."),
    )
    # Forty newer unrelated task links used to push this exact prior decision
    # and its result outside both the lookup page and the request text budget.
    unrelated: list[Decision] = []
    for index in range(45):
        task_id = f"orion-{index}"
        prompt = "Orion unrelated work " + "detail " * 200
        tasks.submit(task_id, "Orion task", prompt, RequestSource("other"), at=20 + index / 100)
        unrelated.append(
            Decision(
                task_id,
                "reply",
                "other",
                "revision",
                "Orion",
                "Another project",
                "Orion " + "decision " * 130,
                31 + index / 100,
                Handoff(task_id, prompt),
            )
        )
    board = Board(enabled=True, items=(item,), history=(decision, *unrelated))
    working = work.read(board, source.title + " " + source.body, 50).describe(board)
    with fake_endpoint() as endpoint:
        endpoint.replies = [says(output(([source.identity], "action")))]
        classify(Settings(endpoint.url, "fixture", "transcribe", "quick", "agent", "", ""), (source,), (), working_context=working, clock=lambda: 50)
        payload = _OBJECT.validate_json(endpoint.last.body)
    assert payload["model"] == "agent"
    match payload:
        case {"instructions": str() as instructions, "input": [{"content": str() as evidence}]}:
            review = REVIEW_INPUT.validate_json(evidence)
        case _:
            raise AssertionError("The feed review lost its typed request.")
    assert source.body not in instructions and review.candidates[0].body == source.body
    for expected in (
        "Explain the tradeoff",
        "approved baseline",
        "supplier costs",
        "Use the approved forecast.",
        "excel.exe",
        "last month's estimate",
    ):
        assert expected in review.working_context
    assert "Unrelated secret" not in working and "obsolete total" not in working
    assert "atlas/old" in working


def test_registered_reply_tool_saves_instruction_before_handoff_and_reuses_it_after_restart(tmp_path: Path) -> None:
    # Defect: treating a reply as a cosmetic update, dropping it on restart,
    # queueing before saving, or accepting a stale/different reply under the same ID.
    tasks, claim, clock = claimed(tmp_path)
    source = captured("atlas", Excerpt("Atlas review", "Explain the supplier variance.", 1))
    item = decode(output(([source.identity], "action")), (source,))[0]
    feed_store = MemoryStore()
    feed_store.data = saved(Board(enabled=True, items=(item,)))
    submitted: list[tuple[str, str, Profile]] = []
    words = "Compare Atlas against the approved forecast and write the supplier explanation."

    def queue(task: str, prompt: str, profile: Profile) -> None:
        stored = restored(feed_store.read())
        assert stored.history[-1].text == words, "The handoff ran before the decision was durable."
        submitted.append((task, prompt, profile))
        tasks.submit(task, item.title, prompt, RequestSource("feed", profile), at=clock())

    endpoint = tmp_path / "bridge.json"
    triage = TriageFixture(feed_store, lambda _batch, _rules: "{}", submit=queue)
    bridge = feed_bridge(endpoint, triage)
    rig = ToolRig(work=WorkExecution(claim, tasks, Resources(), clock=clock), feed_request=lambda data: request(data, endpoint))
    reply = FeedReply(item.identity, proposal_revision(item), "user-turn-one", words)
    arguments = {"item": reply.item, "revision": reply.revision, "reply_id": reply.reply_id, "text": reply.text}
    try:
        wrong = rig.call("work_feed_reply", **{**arguments, "revision": "stale"})
        assert not wrong.ok and not submitted and not triage.board.history
        result = rig.call("work_feed_reply", **arguments)
        assert result.ok and len(submitted) == 1
        task_id, prompt, profile = submitted[0]
        assert words in prompt and "Carry out the user's instruction" in prompt
        assert profile == FeedHandoff(item.identity, item.title)
        assert triage.board.actions == (item,), "Queueing is not completion."
        assert _OBJECT.validate_json(result.text)["queued"] == task_id
    finally:
        bridge.close()
        triage.close()
    restarted = TriageFixture(feed_store, lambda _batch, _rules: "{}", submit=queue)
    try:
        restarted.command(reply)
        assert len(submitted) == 2 and submitted[0] == submitted[1]
        assert len(restarted.board.history) == 1 and tasks.get(task_id) is not None
        # Acknowledgment retries remain bound to the saved instruction even after re-triage.
        restarted.board = replace(restarted.board, items=(replace(item, summary="New reading"),))
        restarted.command(reply)
        assert len(submitted) == 2
        assert isinstance(restarted.command(replace(reply, text="A different instruction.")), FeedRejected)
        assert len(restarted.board.history) == 1
    finally:
        restarted.close()


def test_failed_feed_save_cannot_start_reply_work_and_failed_queue_keeps_retryable_instruction(tmp_path: Path) -> None:
    # Defect: a storage error starts unrecorded work; a queue error loses the
    # exact user's instruction or falsely reports a no-change validation rejection.
    source = captured("review", Excerpt("Review", "Please review.", 1))
    item = decode(output(([source.identity], "action")), (source,))[0]

    class FailedStore(MemoryStore):
        def write(self, state: StoredBoard) -> None:
            raise OSError("Storage unavailable")

    broken = FailedStore()
    broken.data = saved(Board(enabled=True, items=(item,)))
    submitted: list[str] = []
    command = FeedReply(item.identity, proposal_revision(item), "reply", "Check the totals.")
    failed = TriageFixture(
        broken,
        lambda _batch, _rules: "{}",
        submit=lambda task, _prompt, _profile: submitted.append(task),
    )
    try:
        with TestCase().assertRaises(OSError):
            failed.command(command)
        assert not submitted and not failed.board.history
    finally:
        failed.close()

    def unavailable(_task: str, _prompt: str, _profile: Profile) -> None:
        raise ValueError("Work queue unavailable")

    store = MemoryStore()
    store.data = saved(Board(enabled=True, items=(item,)))
    queued = TriageFixture(store, lambda _batch, _rules: "{}", submit=unavailable)
    try:
        with TestCase().assertRaises(OSError):
            queued.command(command)
        assert len(restored(store.read()).history) == 1
        assert not queued.submitted and queued.board.actions == (item,)
    finally:
        queued.close()


def test_context_changes_reconsider_open_work_without_reopening_handled_items(tmp_path: Path) -> None:
    # Defect: same-day source caching ignores a new saved decision or completed
    # task; context refresh revives work the user already dismissed.
    source = captured("one", Excerpt("Atlas", "Review the variance.", 1))
    day = datetime.fromtimestamp(50, UTC).date()
    item = replace(decode(output(([source.identity], "action")), (source,))[0], reviewed_on=day)
    store = MemoryStore()
    store.data = saved(Board(enabled=True, items=(replace(item, disposition=Disposition.QUIET),)))
    triage = TriageFixture(store, lambda _batch, _rules: "{}")
    try:
        assert not unassessed(triage.board, (source,), today=day)
        triage.context_changed((), ())
        epoch = triage.epoch
        triage.context_changed((), ())
        assert triage.epoch == epoch
        triage.context_changed((), (Preference("style", "Style", "Use the baseline.", "Jim", 10),))
        assert triage.epoch == epoch + 1 and unassessed(triage.board, (source,), today=day) == (source,)
        triage.edit(DismissItem(item.identity))
        triage.context_changed((), ())
        assert not triage.board.actions
        assert triage.board.history[-1].kind == "dismiss"
    finally:
        triage.close()
