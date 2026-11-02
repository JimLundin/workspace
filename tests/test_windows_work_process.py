"""Isolated native worker lifetimes, real journals, local pipes, and HWND cleanup."""

import contextlib
import os
import socket
import subprocess
import sys
import threading
import unittest
import uuid
from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path
from typing import cast

if sys.platform != "win32":
    raise unittest.SkipTest("Windows work process ownership")

from assistant.feed_contracts import FeedCommand
from assistant.feed_triage_service import Triage
from assistant.work_agent import WorkAgent
from assistant.work_bridge import WorkOwners, answer
from assistant.work_bridge_contracts import FeedResponse
from assistant.work_snapshot import WorkSnapshot
from automation import ipc
from automation.bridge import BridgeClient, read_discovery
from automation.context import ContextStore
from automation.profile_lease import ProfileLease
from automation.routines import Disabled, RoutineStore
from automation.store import TaskStore
from automation.task import Completed, Interrupted, RequestSource, Running, RunRef, Task
from automation.work_folder import WorkFolder
from tests.feed_fixture import no_canvas, no_personal_work
from tests.test_agent_window import RecordingWindow
from tests.test_feed_triage_service import MemoryStore
from winapi import system, windows

ROOT = Path(__file__).resolve().parent.parent
_PROGRAM = r"""
import os, socket, sys, threading
from pathlib import Path
from runtime import activate
activate()
from automation.app import CallOwner, OwnerCalls, run
from automation.store import TaskStore
from automation.task import Completed, Interrupted, Running
from assistant.llm import Missing
from assistant.feed_contracts import SaveRule
from winapi import windows

folder, title, port, mode = Path(sys.argv[1]), sys.argv[2], int(sys.argv[3]), sys.argv[4]
channel = socket.create_connection(("127.0.0.1", port), timeout=10)
lock = threading.Lock()
def notify(message):
    with lock:
        channel.sendall((message + "\n").encode("utf-8"))

notify("pid:" + str(os.getpid()))

class Execution:
    def __init__(self, bridge):
        self.calls = OwnerCalls(bridge)

    def run_work(self, claim, store, log, stop):
        if mode == "link":
            assert claim.task.prompt == "Link check"
            notify("claimed:" + claim.run.run_id)
            assert channel.recv(1) == b"s", "The test did not release live progress."
            log.say("Linked progress.")
            self.calls.current = CallOwner(claim.run, stop)
            try:
                response = self.calls.desktop(SaveRule("Keep linked fixture updates quiet."))
                assert "Keep linked fixture updates quiet." in response
            finally:
                self.calls.current = None
            notify("said:" + claim.run.run_id)
            assert channel.recv(1) == b"f", "The test did not release completion."
            # No live Done: the controller must save the returned outcome.
            return Completed("Linked result.", ())
        assert isinstance(claim.previous, Interrupted), claim.previous
        assert claim.task.checkpoint.summary == "Read and checked the transcript."
        # A real execution-owned file is closed before controller.wait returns.
        with (folder / "execution-resource.txt").open("w", encoding="utf-8") as resource:
            resource.write(claim.run.run_id)
            resource.flush()
            log.step("Awaiting the native shutdown request.")
            notify("claimed:" + claim.run.run_id)
            assert stop.wait(20), "The worker did not cancel its execution adapter."
        notify("cleaned:" + claim.run.run_id)
        return Completed("Adapter returned while shutting down.", ("Owned file released.",))

def ready():
    hwnd = windows.find(title)
    assert hwnd and windows.process_id(hwnd) == os.getpid()
    for module in ("assistant.app", "assistant.desktop", "desktop_ui.ui", "winapi.audio", "winapi.recording", "tkinter", "PySide6"):
        assert not any(name == module or name.startswith(module + ".") for name in sys.modules), module
    if mode == "fixture":
        task = TaskStore(folder / "work.sqlite3").get("notes")
        assert task is not None
        assert not isinstance(task.state, Running) or task.state.owner != "dead-worker", "Readiness preceded recovery."
    notify("ready")

try:
    run(Missing(("OPENAI_API_KEY",)), folder=folder, title=title, ready=ready,
        execution_factory=Execution if mode in ("fixture", "link") else None)
    assert windows.find(title) is None, "The worker's native HWND survived cleanup."
    notify("closed")
finally:
    channel.close()
"""


@dataclass(slots=True)
class NativeWorker:
    process: subprocess.Popen[bytes]
    peer: socket.socket
    title: str
    process_id: int

    def receive(self) -> str:
        message = bytearray()
        while len(message) < 256:
            character = self.peer.recv(1)
            if not character:
                stdout, stderr = self.process.communicate(timeout=5)
                raise AssertionError((stdout + stderr).decode("utf-8", errors="replace"))
            if character == b"\n":
                return message.decode("utf-8")
            message.extend(character)
        raise AssertionError("The worker fixture sent an unbounded status.")

    def close_window(self) -> None:
        hwnd = windows.find(self.title)
        assert hwnd is not None and windows.process_id(hwnd) == self.process_id
        assert system.post_message(hwnd, system.WM_CLOSE, 0, 0)


@contextlib.contextmanager
def worker(folder: Path, *, mode: str) -> Generator[NativeWorker]:
    title = "workspace automation test " + uuid.uuid4().hex
    with socket.create_server(("127.0.0.1", 0)) as server:
        server.settimeout(12)
        port = cast(tuple[str, int], server.getsockname())[1]
        environment = dict(os.environ, LOCALAPPDATA=str(folder / "profile"), OPENAI_API_KEY="", OPENAI_BASE_URL="", PYTHONUTF8="1")
        process: subprocess.Popen[bytes] = subprocess.Popen(
            [sys.executable, "-c", _PROGRAM, str(folder), title, str(port), mode],
            cwd=ROOT,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            peer, _address = server.accept()
            with peer:
                peer.settimeout(12)
                native = NativeWorker(process, peer, title, process.pid)
                identity = native.receive()
                assert identity.startswith("pid:") and identity[4:].isdecimal()
                native.process_id = int(identity[4:])
                yield native
        finally:
            if process.poll() is None:
                process.kill()  # Only this isolated fixture child; never the desktop Workspace.
            stdout, stderr = process.communicate(timeout=10)
        assert process.wait(timeout=10) == 0, (stdout + stderr).decode("utf-8", errors="replace")


def test_native_worker_recovers_parks_and_restarts_without_ui_or_audio(tmp_path: Path) -> None:
    tasks = TaskStore(tmp_path / "work.sqlite3")
    tasks.submit("notes", "Meeting notes", "Prepare meeting notes.", RequestSource("conversation"), at=1)
    first = tasks.claim("dead-worker", "abruptly-lost-run", at=2)
    assert first is not None
    tasks.progress(first.run, "Read and checked the transcript.", at=3)
    previous = first.run
    for _ in range(2):
        with worker(tmp_path, mode="fixture") as native:
            signals = {native.receive(), native.receive()}
            assert "ready" in signals
            claimed = next(message.removeprefix("claimed:") for message in signals if message.startswith("claimed:"))
            active = tasks.get("notes")
            assert active is not None and isinstance(active.state, Running)
            assert active.state.run == RunRef("notes", claimed) and active.state.run != previous
            with unittest.TestCase().assertRaises(OSError), ProfileLease(tmp_path):
                raise AssertionError("A second process acquired the active worker profile.")
            client = BridgeClient(tmp_path)
            try:
                assert client.connect() == read_discovery(tmp_path).epoch
                client.wake()
            finally:
                client.close()
            native.close_window()
            assert native.receive() == "cleaned:" + claimed
            assert native.receive() == "closed"
            assert native.process.wait(timeout=10) == 0
            previous = RunRef("notes", claimed)
        parked = tasks.get("notes")
        assert parked is not None and isinstance(parked.state, Interrupted)
        assert parked.state.run == previous
        assert parked.checkpoint is not None and parked.checkpoint.summary == "Read and checked the transcript."
        assert (tmp_path / "execution-resource.txt").read_text(encoding="utf-8") == previous.run_id
        assert not (tmp_path / "worker.json").exists()


def test_native_worker_constructs_default_machine_and_disabled_routine(tmp_path: Path) -> None:
    with worker(tmp_path, mode="native") as native:
        assert native.receive() == "ready"
        client = BridgeClient(tmp_path)
        try:
            assert client.connect() == read_discovery(tmp_path).epoch
            assert client.poll()
        finally:
            client.close()
        routines = RoutineStore(tmp_path / "work.sqlite3").list()
        assert len(routines) == 1 and isinstance(routines[0].state, Disabled)
        native.close_window()
        assert native.receive() == "closed"
        assert native.process.wait(timeout=10) == 0


class LinkedOwners:
    """Own the fixture's feed store and publish immutable call observations."""

    __slots__ = ("desktop", "operations", "triage")

    def __init__(self) -> None:
        self.triage = Triage(MemoryStore(), lambda _batch, _rules: "")
        self.operations: tuple[FeedCommand, ...] = ()
        self.desktop = WorkOwners(self.feed, no_personal_work, no_canvas)

    def feed(self, command: FeedCommand) -> FeedResponse:
        self.operations = (*self.operations, command)
        return self.triage.command(command)

    def meeting(self, _operation: ipc.MeetingOperation) -> ipc.OwnerResult:
        raise AssertionError("This fixture requests only the desktop owner.")

    def answer(self, call: ipc.OwnerCall) -> ipc.OwnerResult:
        return answer(call, self.desktop, self.meeting)

    def close(self) -> None:
        self.triage.close()


def linked_claim(snapshot: WorkSnapshot, epoch: str, claimed: str) -> tuple[Task, RunRef]:
    """The native claim and frontend observation must agree before releasing work."""
    (active,) = snapshot.tasks
    assert active.prompt == "Link check"
    match active.state:
        case Running(run=run, owner=owner):
            assert owner == epoch and run == RunRef(active.id, claimed.removeprefix("claimed:"))
            return active, run
        case state:
            raise AssertionError(f"The native worker did not own a running task: {state}")


def test_assistant_submission_runs_in_the_native_worker_and_completes(tmp_path: Path) -> None:
    # Defects: mismatched journals or worker epochs, wrongly fenced live output,
    # or frontend completion that requires a live Done instead of the journal.
    tasks = TaskStore(WorkFolder(tmp_path).journal)
    panels: list[RecordingWindow] = []
    errors: list[str] = []
    completed = threading.Event()
    owners = LinkedOwners()

    def window(agent: WorkAgent) -> RecordingWindow:
        panel = RecordingWindow(agent.stop, on_submit=agent.start, on_reset=agent.new_conversation)
        panels.append(panel)
        return panel

    def published(snapshot: WorkSnapshot) -> None:
        for task in snapshot.tasks:
            match task.state:
                case Completed():
                    completed.set()
                case _:
                    pass

    with worker(tmp_path, mode="link") as native:
        assert native.receive() == "ready"
        epoch = read_discovery(tmp_path).epoch
        agent = WorkAgent(
            tasks,
            RoutineStore(tasks.path),
            ContextStore(tasks.path),
            BridgeClient(tmp_path),
            window,
            on_snapshot=published,
            on_done=lambda: None,
            report_error=errors.append,
            owners=owners.answer,
        )
        agent.start_worker()
        try:
            agent.start("Link check")
            claimed = native.receive()
            assert claimed.startswith("claimed:")
            assert agent.refresh().wait(5), "The frontend did not observe the worker's claim."
            active, run = linked_claim(agent.snapshot(), epoch, claimed)

            native.peer.sendall(b"s")
            assert native.receive() == "said:" + run.run_id
            assert agent.refresh().wait(5), "The frontend did not consume the worker's live progress."
            assert "Linked progress." in panels[0].all_text()
            assert len(owners.operations) == 1
            assert owners.triage.board.rules == ("Keep linked fixture updates quiet.",)
            assert agent.snapshot().tasks[0].state == active.state

            native.peer.sendall(b"f")
            assert completed.wait(5), "The frontend did not publish the worker's durable completion."
            (finished,) = agent.snapshot().tasks
            assert finished.id == active.id and finished.state == Completed("Linked result.", ())
            assert tasks.get(finished.id) == finished
            assert "Linked result." in panels[0].all_text()
            assert not errors
        finally:
            agent.close()
            assert agent.wait_closed(5)
            owners.close()
            for panel in panels:
                panel.paint()
        native.close_window()
        assert native.receive() == "closed"
        assert native.process.wait(timeout=10) == 0
