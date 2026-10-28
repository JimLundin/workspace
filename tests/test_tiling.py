"""Tiling IPC validation, captured targets, and owned manager lifetime without real windows."""

import json
import subprocess
from collections.abc import Sequence
from pathlib import Path
from unittest import TestCase

from assistant.tiling import GlazeWM, ManagedProcess, reply, scoped_config, window_handles, window_id

IDENTITY = "a955f57a-f482-48a1-8132-e6f62aa827c5"


class Process:
    """A fixture owns a process's mutable lifetime and observations of its cleanup."""

    def __init__(self, code: int | None = None) -> None:
        self.pid = 73
        self.code = code
        self.killed = False
        self.waits: list[float] = []

    def poll(self) -> int | None:
        return self.code

    def wait(self, timeout: float) -> int:
        self.waits.append(timeout)
        self.code = 0
        return 0

    def kill(self) -> None:
        self.killed = True
        self.code = 1


class ManagerPeer:
    """An isolated command peer owns manager state, so commands change later queries.

    Its mutable command observations belong to this test's disposable process
    environment; no production module or method is replaced.
    """

    def __init__(self, *, paused: bool | None = False) -> None:
        self.pause_state = paused
        self.windows: object = {"windows": [{"id": IDENTITY, "handle": 42}]}
        self.commands: list[tuple[str, ...]] = []
        self.starts: list[tuple[str, ...]] = []
        self.process = Process()
        self.start_enabled = True
        self.start_succeeds = True
        self.answer: str | None = None
        self.error: subprocess.TimeoutExpired | None = None
        self.now = 0.0

    def run(self, arguments: Sequence[str]) -> subprocess.CompletedProcess[str]:
        args = tuple(arguments[1:])
        if self.error is not None:
            raise self.error
        if self.answer is not None:
            body = self.answer
        elif args == ("query", "paused"):
            body = json.dumps({"success": self.pause_state is not None, "data": self.pause_state})
        elif args == ("query", "windows"):
            body = json.dumps({"success": True, "data": self.windows})
        else:
            assert args[0] == "command"
            self.commands.append(args)
            if args == ("command", "wm-toggle-pause"):
                self.pause_state = not self.pause_state
            elif args == ("command", "wm-exit"):
                self.pause_state = None
                self.process.code = 0
            body = '{"success":true}'
        return subprocess.CompletedProcess(list(arguments), 0, body, "")

    def launch(self, arguments: Sequence[str]) -> ManagedProcess:
        self.starts.append(tuple(arguments))
        if self.start_succeeds:
            self.pause_state = False
        return self.process

    def enabled(self) -> bool:
        return self.start_enabled

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def manager(folder: Path, peer: ManagerPeer) -> GlazeWM:
    binary = folder / "glazewm.exe"
    binary.touch()
    (folder / "cli").mkdir()
    (folder / "cli" / "glazewm.exe").touch()
    return GlazeWM(binary, folder / "config.yaml", runtime=peer)


def test_success_is_owned_by_json_even_when_process_exits_zero(tmp_path: Path) -> None:
    peer = ManagerPeer()
    peer.answer = '{"success":false,"error":"No focused window"}'
    wm = manager(tmp_path, peer)
    with TestCase().assertRaisesRegex(OSError, "No focused window"):
        wm.exchange(("command", "toggle-floating"))
    assert reply('{"success":true,"data":false}') is False
    for body in ("", "[]", "{}", '{"success":1}', '{"success":false}'):
        with TestCase().assertRaises(OSError):
            reply(body)


def test_window_identity_uses_the_captured_handle_and_validates_external_ids() -> None:
    data = {"windows": [{"id": IDENTITY, "handle": 42}, {"id": IDENTITY, "handle": 99, "hasFocus": True}]}
    assert window_id(data, 42) == IDENTITY
    assert window_id(data, 100) is None
    for invalid in (None, {}, {"windows": None}, {"windows": [None]}, {"windows": [{"handle": 42, "id": "bad"}]}):
        with TestCase().assertRaises(OSError):
            window_id(invalid, 42)


def test_managed_handles_validate_the_catalog_boundary() -> None:
    assert window_handles({'windows': [{'handle': 1}, {'handle': 2}]}) == frozenset({1, 2})
    for bad in (None, {}, {'windows': [None]}, {'windows': [{'handle': True}]}, {'windows': [{'handle': 0}]}):
        with TestCase().assertRaises(OSError):
            window_handles(bad)


def test_existing_manager_is_borrowed_and_its_config_and_lifetime_are_preserved(tmp_path: Path) -> None:
    peer = ManagerPeer(paused=True)
    wm = manager(tmp_path, peer)
    original = ("window_rules:\n  - commands: ['ignore']\n    match:\n"
                "      - window_title: { regex: '(?i)^workspace(?:\\b| ·)' }\n").encode()
    wm.config.write_bytes(original)
    wm.start()
    wm.close()
    assert not peer.starts and not peer.commands
    assert peer.pause_state is True
    assert wm.process is None and wm.config.read_bytes() == original


def test_owned_paused_manager_is_resumed_before_exit_and_keeps_user_config(tmp_path: Path) -> None:
    peer = ManagerPeer(paused=None)
    wm = manager(tmp_path, peer)
    wm.config.write_text("personal tiling preferences\n")
    wm.start()
    assert wm.process is peer.process and wm.config.read_text() == "personal tiling preferences\n"
    assert peer.starts == [(str(wm.binary), 'start', '--config', str(wm.config))]
    peer.pause_state = True
    wm.close()
    assert peer.commands == [("command", "wm-toggle-pause"), ("command", "wm-exit")]
    assert peer.process.waits == [5] and not peer.process.killed and wm.process is None
    wm.close()
    assert len(peer.commands) == 2


def test_owned_start_scopes_workspace_titles_to_the_workspace_runtime(tmp_path: Path) -> None:
    peer = ManagerPeer(paused=None)
    wm = manager(tmp_path, peer)
    broad = "      - window_title: { regex: '(?i)^(?:toolkit|workspace)(?:\\b| ·)' }\n"
    personal = "gaps:\n  inner_gap: 7px\nwindow_rules:\n  - commands: ['ignore']\n    match:\n" + broad
    wm.config.write_text(personal)
    wm.start()
    configured = wm.config.read_text()
    assert "inner_gap: 7px" in configured
    assert "      - window_title: { regex: '(?i)^workspace(?:\\b| ·)' }\n        window_process: { regex: '^pythonw?$' }" in configured
    assert "toolkit|workspace" not in configured


def test_config_repair_preserves_custom_rules_and_source_bytes() -> None:
    for ending in (b"\n", b"\r\n"):
        title = "      - window_title: { regex: '(?i)^workspace(?:\\b| ·)' }".encode()
        generated = ending.join((b"window_rules:", b"  - commands: ['ignore']", b"    match:", title, b""))
        repaired = scoped_config(generated)
        assert repaired == generated + b"        window_process: { regex: '^pythonw?$' }" + ending
        assert scoped_config(repaired) == repaired
        custom = generated + b"        window_process: { equals: 'my-app' }" + ending
        commented = b"#" + generated.replace(ending, ending + b"#")
        separated_custom = generated + ending + b"        window_process: { equals: 'my-app' }" + ending
        for untouched in (custom, separated_custom, commented, generated.replace(b"['ignore']", b"['set-floating']")):
            assert scoped_config(untouched) == untouched


def test_failed_start_releases_ownership_and_disabled_tiling_does_not_launch(tmp_path: Path) -> None:
    peer = ManagerPeer(paused=None)
    peer.start_succeeds = False
    peer.process.code = 1
    wm = manager(tmp_path, peer)
    with TestCase().assertRaisesRegex(OSError, "could not start"):
        wm.start()
    assert wm.process is None and len(peer.starts) == 1
    peer.start_enabled = False
    wm.start()
    assert len(peer.starts) == 1


def test_menu_command_targets_captured_window_and_reports_paused_noops(tmp_path: Path) -> None:
    peer = ManagerPeer()
    wm = manager(tmp_path, peer)
    wm.command(("toggle-floating",), 42)
    assert peer.commands == [("command", "--id", IDENTITY, "toggle-floating")]
    peer.pause_state = True
    with TestCase().assertRaisesRegex(OSError, "paused"):
        wm.command(("toggle-floating",), 42)
    assert len(peer.commands) == 1
    wm.command(("wm-toggle-pause",))
    assert peer.commands[-1] == ("command", "wm-toggle-pause") and peer.pause_state is False


def test_native_snap_falls_back_when_paused_or_target_is_unmanaged(tmp_path: Path) -> None:
    peer = ManagerPeer(paused=True)
    wm = manager(tmp_path, peer)
    assert not wm.arrange(("move", "--direction", "left"), 42)
    assert not peer.commands
    peer.pause_state = False
    peer.windows = {"windows": []}
    assert not wm.arrange(("move", "--direction", "left"), 42)
    assert not peer.commands
    peer.windows = {"windows": [{"id": IDENTITY, "handle": 42}]}
    assert wm.arrange(("move", "--direction", "left"), 42)
    assert peer.commands == [("command", "--id", IDENTITY, "move", "--direction", "left")]


def test_cli_timeout_is_bounded_and_missing_binary_never_launches(tmp_path: Path) -> None:
    peer = ManagerPeer()
    peer.error = subprocess.TimeoutExpired("glazewm", 3)
    wm = manager(tmp_path, peer)
    with TestCase().assertRaisesRegex(OSError, "three seconds"):
        wm.exchange(("query", "paused"))
    wm.cli.unlink()
    wm.start()
    assert not peer.starts


def test_window_switcher_focuses_the_exact_container_including_a_hidden_workspace(tmp_path: Path) -> None:
    peer = ManagerPeer()
    peer.windows = {'windows': [{'id': IDENTITY, 'handle': 42, 'displayState': 'hidden'}]}
    wm = manager(tmp_path, peer)
    assert wm.focus(42)
    assert peer.commands == [('command', 'focus', '--container-id', IDENTITY)]
