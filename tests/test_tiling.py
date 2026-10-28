"""Tiling IPC validation, captured targets, and owned manager lifetime without real windows."""

import os
import subprocess
from pathlib import Path
from unittest import TestCase
from unittest.mock import call, patch

from assistant.tiling import GlazeWM, reply, scoped_config, window_handles, window_id

IDENTITY = "a955f57a-f482-48a1-8132-e6f62aa827c5"


class Process:
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


def manager(folder: Path) -> GlazeWM:
    binary = folder / "glazewm.exe"
    binary.touch()
    (folder / "cli").mkdir()
    (folder / "cli" / "glazewm.exe").touch()
    return GlazeWM(binary, folder / "config.yaml")


def test_success_is_owned_by_json_even_when_process_exits_zero(tmp_path: Path) -> None:
    wm = manager(tmp_path)
    result = subprocess.CompletedProcess([str(wm.cli)], 0, '{"success":false,"error":"No focused window"}', "")
    with patch("assistant.tiling.subprocess.run", return_value=result), TestCase().assertRaisesRegex(OSError, "No focused window"):
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
    wm = manager(tmp_path)
    original = ("window_rules:\n  - commands: ['ignore']\n    match:\n"
                "      - window_title: { regex: '(?i)^workspace(?:\\b| ·)' }\n").encode()
    wm.config.write_bytes(original)
    with patch.object(GlazeWM, "paused", return_value=True), patch("assistant.tiling.launch") as launch, patch.object(GlazeWM, "exchange") as send:
        wm.start()
        wm.close()
        launch.assert_not_called()
        send.assert_not_called()
    assert wm.process is None and wm.config.read_bytes() == original


def test_owned_paused_manager_is_resumed_before_exit_and_keeps_user_config(tmp_path: Path) -> None:
    wm = manager(tmp_path)
    wm.config.write_text("personal tiling preferences\n")
    process = Process()
    with patch.object(GlazeWM, "paused", side_effect=(None, False, True)), patch("assistant.tiling.launch", return_value=process):
        wm.start()
        started = wm.process
        assert started is process and wm.config.read_text() == "personal tiling preferences\n"
        with patch.object(GlazeWM, "exchange", return_value=None) as send:
            wm.close()
            send.assert_has_calls([call(("command", "wm-toggle-pause")), call(("command", "wm-exit"))])
        assert process.waits == [5] and not process.killed and wm.process is None
        wm.close()


def test_owned_start_scopes_workspace_titles_to_the_workspace_runtime(tmp_path: Path) -> None:
    wm = manager(tmp_path)
    broad = "      - window_title: { regex: '(?i)^(?:toolkit|workspace)(?:\\b| ·)' }\n"
    personal = "gaps:\n  inner_gap: 7px\nwindow_rules:\n  - commands: ['ignore']\n    match:\n" + broad
    wm.config.write_text(personal)
    process = Process()
    with patch.object(GlazeWM, "paused", side_effect=(None, False)), patch("assistant.tiling.launch", return_value=process):
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
    wm = manager(tmp_path)
    process = Process(1)
    with (patch.object(GlazeWM, "paused", return_value=None), patch("assistant.tiling.launch", return_value=process),
          TestCase().assertRaisesRegex(OSError, "could not start")):
        wm.start()
    assert wm.process is None
    with patch.object(os, "environ", {"WORKSPACE_TILING": "off"}), patch("assistant.tiling.launch") as launch:
        wm.start()
        launch.assert_not_called()


def test_menu_command_targets_captured_window_and_reports_paused_noops(tmp_path: Path) -> None:
    wm = manager(tmp_path)
    data = {"windows": [{"id": IDENTITY, "handle": 42}]}
    with patch.object(GlazeWM, "paused", return_value=False), patch.object(GlazeWM, "exchange", side_effect=(data, None)) as send:
        wm.command(("toggle-floating",), 42)
        assert send.call_args_list == [call(("query", "windows")), call(("command", "--id", IDENTITY, "toggle-floating"))]
    with patch.object(GlazeWM, "paused", return_value=True), patch.object(GlazeWM, "exchange") as send:
        with TestCase().assertRaisesRegex(OSError, "paused"):
            wm.command(("toggle-floating",), 42)
        send.assert_not_called()
        wm.command(("wm-toggle-pause",))
        send.assert_called_once_with(("command", "wm-toggle-pause"))


def test_native_snap_falls_back_when_paused_or_target_is_unmanaged(tmp_path: Path) -> None:
    wm = manager(tmp_path)
    with patch.object(GlazeWM, "paused", return_value=True), patch.object(GlazeWM, "exchange") as send:
        assert not wm.arrange(("move", "--direction", "left"), 42)
        send.assert_not_called()
    empty: dict[str, object] = {"windows": []}
    with patch.object(GlazeWM, "paused", return_value=False), patch.object(GlazeWM, "exchange", return_value=empty) as send:
        assert not wm.arrange(("move", "--direction", "left"), 42)
        send.assert_called_once_with(("query", "windows"))
    data = {"windows": [{"id": IDENTITY, "handle": 42}]}
    with patch.object(GlazeWM, "paused", return_value=False), patch.object(GlazeWM, "exchange", side_effect=(data, None)) as send:
        assert wm.arrange(("move", "--direction", "left"), 42)
        send.assert_called_with(("command", "--id", IDENTITY, "move", "--direction", "left"))


def test_cli_timeout_is_bounded_and_missing_binary_never_launches(tmp_path: Path) -> None:
    wm = manager(tmp_path)
    with (patch("assistant.tiling.subprocess.run", side_effect=subprocess.TimeoutExpired("glazewm", 3)),
          TestCase().assertRaisesRegex(OSError, "three seconds")):
        wm.exchange(("query", "paused"))
    wm.cli.unlink()
    with patch("assistant.tiling.launch") as launch:
        wm.start()
        launch.assert_not_called()


def test_window_switcher_focuses_the_exact_container_including_a_hidden_workspace(tmp_path: Path) -> None:
    wm = manager(tmp_path)
    data = {'windows': [{'id': IDENTITY, 'handle': 42, 'displayState': 'hidden'}]}
    with patch.object(GlazeWM, 'paused', return_value=False), patch.object(GlazeWM, 'exchange', side_effect=(data, None)) as send:
        assert wm.focus(42)
        assert send.call_args_list == [call(('query', 'windows')), call(('command', 'focus', '--container-id', IDENTITY))]
