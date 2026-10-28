"""Hook requests cross the real local transport and keep exact session/answer identity."""

import json
import threading
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.client import HTTPResponse
from pathlib import Path
from typing import cast
from urllib.error import HTTPError
from urllib.request import urlopen

from assistant.console_inbox import ConsoleInbox
from assistant.console_requests import Answer, Dismiss, Provider, Request, State, answered, hook_output, request
from tests.json_fixture import json_object, json_text


def event(provider: Provider, session: str = "fixture-session") -> dict[str, object]:
    tool = "AskUserQuestion" if provider is Provider.CLAUDE else "request_user_input"
    return {"session_id": session, "cwd": "/fictional/project", "hook_event_name": "PreToolUse", "tool_name": tool,
            "tool_input": {"questions": [{"id": "one", "question": "Which sheet?", "options": [{"label": "Revenue", "description": "Use totals"}]}]}}


def post(endpoint: Path, provider: Provider, payload: dict[str, object]) -> object:
    data = cast(dict[str, str], json_object(endpoint.read_text()))
    message_data: dict[str, object] = {"provider": provider.value, "event": payload}
    message = json.dumps(message_data).encode()
    command = urllib.request.Request(json_text(data["url"]), data=message, headers={"Authorization": "Bearer " + data["token"],
                                  "Content-Type": "application/json"})
    with cast(HTTPResponse, urlopen(command, timeout=4)) as response:
        return json_object(response.read())


def test_both_cli_hooks_receive_the_exact_user_answer_over_local_transport(tmp_path: Path) -> None:
    for provider in Provider:
        arrived = threading.Event()
        observed: list[tuple[Request, ...]] = []
        def publish(values: tuple[Request, ...], observed: list[tuple[Request, ...]] = observed, arrived: threading.Event = arrived) -> None:
            observed.append(values)
            arrived.set()
        endpoint = tmp_path / "bridge.json"
        inbox = ConsoleInbox(endpoint, publish, timeout=3)
        try:
            with ThreadPoolExecutor(max_workers=1) as worker:
                raw = event(provider)
                pending = worker.submit(post, endpoint, provider, raw)
                assert arrived.wait(2)
                current = observed[-1][0]
                assert not inbox.command(Answer("wrong-request", 0, "Revenue"))
                assert inbox.command(Answer(current.identity, 0, "Revenue"))
                assert not inbox.command(Answer(current.identity, 0, "Another answer"))
                reply = answered(current, Answer(current.identity, 0, "Revenue"))
                assert reply is not None
                expected = hook_output(provider, raw, reply)
                assert pending.result(3) == expected
                assert observed[-1][0].state is State.ANSWERED
        finally:
            inbox.close()
        assert not endpoint.exists()


def test_permission_requests_cannot_be_approved_by_dismissal_or_free_text(tmp_path: Path) -> None:
    arrived = threading.Event()
    values: list[tuple[Request, ...]] = []
    def publish(current: tuple[Request, ...]) -> None:
        values.append(current)
        arrived.set()
    endpoint = tmp_path / "bridge.json"
    inbox = ConsoleInbox(endpoint, publish, timeout=3)
    try:
        with ThreadPoolExecutor(max_workers=1) as worker:
            raw: dict[str, object] = {"session_id": "fixture", "cwd": "/fictional", "hook_event_name": "PermissionRequest",
                   "tool_name": "Bash", "tool_input": {"command": "echo fixture"}}
            waiting = worker.submit(post, endpoint, Provider.CLAUDE, raw)
            assert arrived.wait(2)
            current = values[-1][0]
            assert not inbox.command(Answer(current.identity, 0, "sure"))
            assert inbox.command(Dismiss(current.identity))
            assert waiting.result(2) == {}
            assert values[-1][0].state is State.EXPIRED
    finally:
        inbox.close()


def test_interruption_releases_only_its_exact_console_session(tmp_path: Path) -> None:
    arrived = threading.Event()
    values: list[tuple[Request, ...]] = []
    def publish(current: tuple[Request, ...]) -> None:
        values.append(current)
        if len(current) == 2:
            arrived.set()
    endpoint = tmp_path / "bridge.json"
    inbox = ConsoleInbox(endpoint, publish, timeout=3)
    try:
        with ThreadPoolExecutor(max_workers=2) as worker:
            first = worker.submit(post, endpoint, Provider.CODEX, event(Provider.CODEX, "first"))
            second = worker.submit(post, endpoint, Provider.CODEX, event(Provider.CODEX, "second"))
            assert arrived.wait(2)
            assert post(endpoint, Provider.CODEX, {"hook_event_name": "Interrupt", "session_id": "first"}) == {}
            assert first.result(2) == {} and not second.done()
            remaining = next(item for item in values[-1] if item.session == "second")
            assert inbox.command(Answer(remaining.identity, 0, "Revenue"))
            assert second.result(2) != {}
    finally:
        inbox.close()


def test_transport_rejects_unauthenticated_requests_and_close_restores_native_prompt(tmp_path: Path) -> None:
    arrived = threading.Event()
    endpoint = tmp_path / "bridge.json"
    inbox = ConsoleInbox(endpoint, lambda _: arrived.set(), timeout=3)
    try:
        location = json_text(json_object(endpoint.read_text())["url"])
        try:
            urlopen(urllib.request.Request(location, data=b"{}"), timeout=2)
        except HTTPError as error:
            assert error.code == 403
        else:
            raise AssertionError("An unauthenticated request was accepted.")
        with ThreadPoolExecutor(max_workers=1) as worker:
            waiting = worker.submit(post, endpoint, Provider.CODEX, event(Provider.CODEX))
            assert arrived.wait(2)
            inbox.close()
            assert waiting.result(2) == {}
    finally:
        if not inbox.closed.is_set():
            inbox.close()


def test_multi_question_answering_retains_prior_answers_and_rejects_an_unrelated_request() -> None:
    raw = event(Provider.CLAUDE)
    raw["tool_input"] = {"questions": [{"question": "Which sheet?"}, {"question": "Which year?"}]}
    current = request(Provider.CLAUDE, raw, "owned", 1)
    first = answered(current, Answer("owned", 0, "Revenue"))
    assert first is not None and first.state is State.WAITING
    assert answered(first, Answer("other", 1, "2026")) is None
    second = answered(first, Answer("owned", 1, "2026"))
    assert second is not None and second.state is State.ANSWERED
    assert dict(second.answers) == {0: "Revenue", 1: "2026"}
