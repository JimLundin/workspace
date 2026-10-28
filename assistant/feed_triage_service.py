"""Coalesced automatic triage and an authenticated local seam for the voice agent."""

import contextlib
import hmac
import json
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from itertools import chain, islice
from pathlib import Path
from typing import Protocol, assert_never, cast

from assistant import llm
from assistant.communications import Feed, SourceDate, SourceDateHint, SourceDateStatus
from assistant.console_requests import Answer, Command, Request, State, object_value, text
from assistant.feed_triage import (
    INSTRUCTIONS,
    Board,
    Candidate,
    Disposition,
    applied,
    batch_for,
    collect,
    decode,
    edited,
    reconcile,
    restored,
    retimed,
    saved,
    selected,
    solution_task,
    timestamp_text,
    timing_changes,
    unassessed,
)
from assistant.llm import Json, Settings


class RejectedError(ValueError):
    """The owner refused validation before changing any state."""

    __slots__ = ()


class Store(Protocol):
    def read(self) -> dict[str, Json]: ...
    def write(self, state: dict[str, Json]) -> None: ...


def source_context(item: Candidate) -> dict[str, Json]:
    """Serialize source date evidence, keeping observation time out of creation time."""
    match item.source_time:
        case SourceDate(at):
            created, hint, observed_on = timestamp_text(at), None, None
        case SourceDateHint(label, day):
            created, hint, observed_on = None, label, day.isoformat()
        case SourceDateStatus.UNKNOWN:
            created, hint, observed_on = None, None, None
        case _ as unreachable:
            assert_never(unreachable)
    return {'id': item.identity, 'revision': item.revision, 'source': item.source, 'title': item.title, 'body': item.body,
            'created_at': created, 'date_hint': hint, 'date_hint_observed_on': observed_on}


def classify(settings: Settings, batch: tuple[Candidate, ...], rules: tuple[str, ...], *,
             clock: Callable[[], float] = time.time) -> str:
    # The model request combines its settings, evidence and saved policy with a
    # fresh clock observation; the request owner supplies that effect explicitly.
    now = datetime.fromtimestamp(clock(), UTC).astimezone()
    payload: dict[str, Json] = {'reviewed_at': now.isoformat(), 'candidates': list[Json](source_context(item) for item in batch)}
    visibility: list[str] = list(rules)
    instructions = INSTRUCTIONS + '\nSaved visibility preferences (JSON):\n' + json.dumps(visibility, ensure_ascii=False)
    messages = (llm.system_message(instructions), llm.user_message(json.dumps(payload, ensure_ascii=False)))
    reply = llm.chat(settings, messages, timeout_s=45)
    if isinstance(reply, llm.Failure):
        raise OSError('Work-feed triage could not reach the configured model.')
    return reply.text


def open_bridge(handler: type[BaseHTTPRequestHandler]) -> ThreadingHTTPServer:
    return ThreadingHTTPServer(('127.0.0.1', 0), handler)


def wait_for_stop(stopped: threading.Event, seconds: float) -> bool:
    return stopped.wait(seconds)


class Triage:
    __slots__ = (
        'board',
        'candidates',
        'clock',
        'closed',
        'console',
        'endpoint',
        'epoch',
        'feed',
        'lock',
        'model',
        'publish',
        'requests',
        'server',
        'server_thread',
        'store',
        'submit',
        'submitted',
        'thread',
        'token',
        'wait',
        'wake',
    )

    def __init__(self, endpoint: Path, store: Store, publish: Callable[[Board], None],
                 model: Callable[[tuple[Candidate, ...], tuple[str, ...]], str], console: Callable[[Command], bool], *,
                 submit: Callable[[str, str], None] | None = None,
                 server_factory: Callable[[type[BaseHTTPRequestHandler]], ThreadingHTTPServer] = open_bridge,
                 wait: Callable[[threading.Event, float], bool] = wait_for_stop,
                 clock: Callable[[], float] = time.time) -> None:
        # Compose the real storage, model, voice and HTTP effects here. Server
        # construction and cancellable delays vary independently in native and
        # deterministic adapters, so each is an explicit dependency.
        self.endpoint, self.store, self.publish, self.model, self.console = endpoint, store, publish, model, console
        self.wait: Callable[[threading.Event, float], bool] = wait
        self.clock: Callable[[], float] = clock
        self.submit = submit
        self.submitted: set[str] = set()
        self.lock = threading.RLock()
        self.closed, self.wake = threading.Event(), threading.Event()
        self.feed = Feed()
        self.requests: tuple[Request, ...] = ()
        self.candidates: tuple[Candidate, ...] = ()
        self.epoch = 0
        try:
            self.board: Board = restored(store.read())
        except (ValueError, OSError):
            self.board = Board(enabled=True, status='Saved feed preferences could not be loaded.')
        self.token = secrets.token_urlsafe(32)
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: object) -> None:
                pass

            def do_POST(self) -> None:
                if self.path != '/feed' or not hmac.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + owner.token):
                    self.send_error(403)
                    return
                try:
                    length = int(self.headers.get('Content-Length', '0'))
                    if not 0 < length <= 64000:
                        raise ValueError('Invalid feed payload size.')
                    data = object_value(cast(object, json.loads(self.rfile.read(length))))
                    result = owner.command(data)
                except RejectedError as error:
                    result = {'accepted': False, 'error': str(error)}
                except (ValueError, TypeError):
                    self.send_error(400)
                    return
                except OSError:
                    self.send_error(503)
                    return
                output = json.dumps(result, ensure_ascii=False).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(output)))
                self.end_headers()
                with contextlib.suppress(BrokenPipeError, ConnectionResetError):
                    self.wfile.write(output)

        self.server = server_factory(Handler)
        self.server.daemon_threads = True
        address = cast(tuple[str, int], self.server.socket.getsockname())
        endpoint.parent.mkdir(parents=True, exist_ok=True)
        temporary = endpoint.with_suffix('.tmp')
        configuration: dict[str, str] = {'url': f'http://127.0.0.1:{address[1]}/feed', 'token': self.token}
        temporary.write_text(json.dumps(configuration), encoding='utf-8')
        temporary.chmod(0o600)
        temporary.replace(endpoint)
        self.server_thread = threading.Thread(target=self.server.serve_forever, name='Work feed bridge', daemon=True)
        self.thread = threading.Thread(target=self.run, name='Work feed triage', daemon=True)
        self.server_thread.start()
        self.thread.start()
        self.publish(self.board)

    def observe(self, feed: Feed, requests: tuple[Request, ...]) -> None:
        with self.lock:
            self.feed, self.requests = feed, requests
            candidates = collect(feed, requests)
            if candidates == self.candidates:
                return
            changed = timing_changes(self.candidates, candidates)
            if changed:
                self.board = retimed(self.board, changed)
                self.epoch += 1
            self.candidates = candidates
            self.board = reconcile(self.board, candidates)
            self.publish(self.board)
            self.wake.set()

    def snapshot(self) -> dict[str, Json]:
        with self.lock:
            actions = self.board.actions
            result = saved(replace(self.board, items=actions[:40]), suggestions=True)
            result['reviewed_at'] = datetime.fromtimestamp(self.clock(), UTC).astimezone().isoformat()
            decisions: list[Json] = [{'item': item.identity, 'title': item.title, 'reason': item.decision}
                                     for item in self.board.items if item.disposition is Disposition.REJECTED]
            result['decisions'] = decisions[-40:]
            result['total_actions'] = len(actions)
            result['quiet_updates'] = sum(item.disposition.value == 'quiet' for item in self.board.items)
            result['focus'] = actions[0].identity if actions else None
            result['status'] = self.board.status
            result['pending'] = self.board.pending
            current = {(item.identity, item.revision) for item in self.candidates}
            unavailable: list[Json] = []
            for proposal in actions:
                if not all(ref in current for ref in proposal.references):
                    unavailable.append(proposal.identity)
            result['unavailable_items'] = unavailable
            result['quiet_reactions'] = self.board.reactions
            wanted = frozenset(ref[0] for item in actions[:40] for ref in item.references)
            ordered = chain((item for item in self.candidates if item.identity in wanted),
                            (item for item in self.candidates if item.identity not in wanted))
            sources: list[Json] = [source_context(item) for item in islice((item for item in ordered if not item.reaction), 80)]
            result['sources'] = sources
            result['console_questions'] = [
                {'id': request.identity, 'provider': request.provider.value, 'title': request.title, 'detail': request.detail,
                 'created_at': timestamp_text(request.created_at),
                 'approval': request.approval, 'questions': [
                     {'index': index, 'text': question.text, 'multiple': question.multiple, 'options': [option.label for option in question.options]}
                     for index, question in enumerate(request.questions) if index not in dict(request.answers)]}
                for request in self.requests if request.state is State.WAITING]
            return result

    def command(self, data: dict[str, object]) -> dict[str, Json]:
        operation = text(data.get('operation'), 32, default='read')
        if operation == 'read':
            return self.snapshot()
        if operation == 'choose':
            return self.choose(data)
        if operation == 'console_answer':
            identity = text(data.get('item'), 128)
            index = data.get('question_index')
            if type(index) is not int:
                raise ValueError('Question index must be an integer.')
            answer = text(data.get('text'), 4096)
            if not self.console(Answer(identity, index, answer)):
                raise RejectedError('The exact console question is no longer waiting or the answer is invalid. Read the feed again.')
            return {'answered': identity, 'question_index': index}
        with self.lock:
            try:
                updated = edited(self.board, data)
            except ValueError as error:
                raise RejectedError(str(error)) from error
            if operation in ('rule', 'forget_rule', 'clear_rules'):
                available = {item.identity for item in self.candidates}
                preserved = tuple(item for item in self.board.items
                                  if item.disposition not in (Disposition.DONE, Disposition.DISMISSED, Disposition.REJECTED)
                                  and all(ref[0] not in available for ref in item.references))
                updated = replace(updated, items=(*updated.items, *preserved))
            updated = reconcile(updated, self.candidates)
            # Save first, so a failed write never claims a preference is durable.
            self.store.write(saved(updated))
            self.board = updated
            self.epoch += 1
            self.publish(self.board)
            self.wake.set()
        return self.snapshot()

    def choose(self, data: dict[str, object]) -> dict[str, Json]:
        with self.lock:
            try:
                item, option = selected(self.board, text(data.get('item'), 128),
                                        text(data.get('revision'), 128), text(data.get('choice'), 32))
            except ValueError as error:
                raise RejectedError(str(error)) from error
            task, prompt = solution_task(item, option)
            if self.submit is None:
                raise RejectedError('The work agent is unavailable. This solution has not been started.')
            if task not in self.submitted:
                # WorkAgent owns durable identified submissions, including retries across restarts.
                # Preserve the exact request on an acknowledgment retry; never claim task completion.
                try:
                    self.submit(task, prompt)
                except ValueError as error:
                    raise RejectedError('The solution could not be queued. Try again.') from error
                self.submitted.add(task)
            return {'accepted': True, 'queued': task, 'item': item.identity, 'choice': option.identity}

    def choose_from_ui(self, identity: str, revision: str, choice: str) -> bool:
        try:
            self.choose({'item': identity, 'revision': revision, 'choice': choice})
        except (RejectedError, OSError):
            return False
        return True

    def dismiss(self, identity: str) -> bool:
        try:
            self.command({'operation': 'dismiss', 'item': identity})
        except (RejectedError, OSError):
            return False
        return True

    def run(self) -> None:
        retry_without: frozenset[str] = frozenset()
        while not self.closed.is_set():
            self.wake.wait(1)
            with self.lock:
                today = datetime.fromtimestamp(self.clock(), UTC).astimezone().date()
                if not self.wake.is_set() and not unassessed(self.board, self.candidates, today=today):
                    continue
            self.wake.clear()
            if self.wait(self.closed, 1.5):
                return
            with self.lock:
                available = tuple(item for item in self.candidates if item.identity not in retry_without)
                today = datetime.fromtimestamp(self.clock(), UTC).astimezone().date()
                batch = batch_for(self.board, available, today=today)
                if not batch and retry_without:
                    retry_without = frozenset[str]()
                    batch = batch_for(self.board, self.candidates, today=today)
                rules, epoch = self.board.rules, self.epoch
                if not batch:
                    continue
                self.board = replace(self.board, status='Considering your work…')
                self.publish(self.board)
            try:
                assessments = tuple(replace(item, reviewed_on=today) for item in decode(self.model(batch, rules), batch))
                with self.lock:
                    if self.closed.is_set():
                        return
                    current = {(item.identity, item.revision) for item in self.candidates}
                    retry_without = frozenset(item.identity for item in batch if (item.identity, item.revision) not in current)
                    if epoch == self.epoch:
                        updated = applied(self.board, assessments, self.candidates)
                        self.store.write(saved(updated))
                        self.board = updated
                        self.publish(self.board)
                    if unassessed(self.board, self.candidates, today=today):
                        self.wake.set()
            except (OSError, ValueError):
                with self.lock:
                    self.board = replace(self.board, status='Triage unavailable · new work awaits review')
                    self.publish(self.board)
                # Existing proposals and exact console questions remain accessible.
                if self.wait(self.closed, 30):
                    return
                self.wake.set()

    def close(self) -> None:
        self.closed.set()
        self.wake.set()
        self.server.shutdown()
        self.server.server_close()
        self.server_thread.join(timeout=2)
        self.thread.join(timeout=2)
        with contextlib.suppress(OSError, ValueError):
            data = object_value(cast(object, json.loads(self.endpoint.read_text(encoding='utf-8'))))
            if data.get('token') == self.token:
                self.endpoint.unlink()
