"""Native automation against an isolated fixture, without user input injection."""

import base64
import json
import sys
import threading
import time
import unittest
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from typing import cast

if sys.platform != "win32":
    raise unittest.SkipTest("Windows computer automation")

import ctypes
import os

from win32more.Windows.Win32.System.StationsAndDesktops import GetThreadDesktop, GetUserObjectInformationW
from win32more.Windows.Win32.UI.WindowsAndMessaging import GetWindowThreadProcessId

from assistant import commands, uia
from assistant.machine import WinMachine
from assistant.uia import Act, Inspect, UiRequest
from contracts.json_value import Json
from tests.test_machine import Browser, Desktop


def decoded(text: str) -> dict[str, Json]:
    data = cast(Json, json.loads(text))
    assert isinstance(data, dict), text
    return data


def powershell_path(path: Path) -> str:
    encoded = base64.b64encode(str(path).encode("utf-8")).decode("ascii")
    return f"[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{encoded}'))"


def desktop_name(thread: int) -> str:
    handle = GetThreadDesktop(thread)
    assert handle is not None
    return object_name(handle)


def object_name(handle: int) -> str:
    buffer = ctypes.create_unicode_buffer(256)
    assert GetUserObjectInformationW(handle, 2, ctypes.addressof(buffer), ctypes.sizeof(buffer), None)
    return buffer.value


@contextmanager
def fixture(folder: Path) -> Generator[int]:
    cancelled = threading.Event()
    source = Path(__file__).with_name("uia_fixture.ps1").read_text(encoding="utf-8")
    script = f"$fixtureRoot = {powershell_path(folder)}\n{source}"
    with ThreadPoolExecutor(max_workers=1) as worker:
        running = worker.submit(commands.powershell, script, timeout_s=100, cancel=cancelled)
        try:
            deadline = time.monotonic() + 15
            while not (folder / "ready").exists():
                assert not running.done(), running.result() if running.done() else "Fixture exited."
                assert time.monotonic() < deadline, "The fixture window did not start."
                time.sleep(0.05)
            handle = decoded((folder / "window.json").read_text())["handle"]
            assert isinstance(handle, int)
            # Defect: a PowerShell child escapes the private test desktop onto the user's.
            assert desktop_name(GetWindowThreadProcessId(handle, None)) == os.environ["WORKSPACE_TEST_DESKTOP"]
            yield handle
        finally:
            (folder / "stop").touch()
            try:
                result = running.result(timeout=5)
            finally:
                cancelled.set()
            assert result[0] == 0, result


def inspect(handle: int, *, query: str = "", limit: int = 100, offset: int = 0) -> dict[str, Json]:
    request = Inspect(handle, query, limit, 10, offset)
    code, text = WinMachine(Desktop(), browser=Browser()).inspect_ui(request, threading.Event())
    assert code == 0, text
    return decoded(text)


def controls(page: dict[str, Json]) -> list[dict[str, Json]]:
    rows = page["controls"]
    assert isinstance(rows, list)
    return [row for row in rows if isinstance(row, dict)]


def control(page: dict[str, Json], name: str) -> dict[str, Json]:
    return next(row for row in controls(page) if row["automation_id"] == f"fixture_{name}")


def batch(folder: Path, requests: list[UiRequest]) -> list[tuple[bool, str]]:
    """Run real UIA scripts in fresh scopes, sharing only PowerShell startup.

    IDs come from an earlier process; a later process verifies the resulting UI.
    Large read results go to a fixture file so combined output cannot be truncated.
    """
    destination = folder / "uia-results.json"
    blocks = [
        "try { $response = & {\n"
        + uia.script(request)
        + "\n}; @{ok=$true; text=[string]$response} } catch { @{ok=$false; text=$_.Exception.Message} }\n"
        for request in requests
    ]
    script = "$results = @(\n" + "".join(blocks) + ")\n"
    script += (
        f"[IO.File]::WriteAllText({powershell_path(destination)}, "
        "(ConvertTo-Json -InputObject $results -Depth 4 -Compress), [Text.UTF8Encoding]::new($false))"
    )
    code, output = commands.powershell(script)
    assert code == 0, output
    data = cast(Json, json.loads(destination.read_text(encoding="utf-8")))
    assert isinstance(data, list) and len(data) == len(requests)
    results: list[tuple[bool, str]] = []
    for row in data:
        assert isinstance(row, dict)
        ok, text = row["ok"], row["text"]
        assert isinstance(ok, bool) and isinstance(text, str)
        results.append((ok, text))
    return results


def test_powershell_preserves_utf8_large_scripts_cwd_and_failure_status(tmp_path: Path) -> None:
    value = 'Åäö "quotes" $literal `value`'
    script = f"$value = '{value}'\n" + "# padding\n" * 5000 + "[Console]::WriteLine($value); [Console]::WriteLine((Get-Location).Path)"
    code, output = commands.powershell(script, cwd=str(tmp_path))
    assert code == 0 and len(output.splitlines()) == 2, output
    assert output.splitlines()[0] == value and Path(output.splitlines()[1]).samefile(tmp_path)
    code, output = commands.powershell("throw 'Fixture error'")
    assert code == 1 and "Fixture error" in output
    code, output = commands.powershell("& $env:ComSpec /c 'exit 7'")
    assert code == 7, output
    code, output = commands.powershell("Write-Warning 'Fixture warning'; Write-Output 'Result'")
    assert code == 0 and "Fixture warning" in output and "Result" in output and "CLIXML" not in output
    code, output = commands.powershell("Start-Sleep -Seconds 60", timeout_s=0.2)
    assert code != 0 and "Timed out" in output


def test_uia_controls_are_inspected_and_operated_across_separate_processes(tmp_path: Path) -> None:
    with fixture(tmp_path) as handle:
        page = inspect(handle)
        rows = controls(page)
        assert len(rows) >= 10
        assert len({str(row["id"]) for row in rows}) == len(rows)
        editor, button = control(page, "editor"), control(page, "button")
        assert "set_value" in cast("list[Json]", editor["actions"])
        value = 'Åäö "literal" $value `value`\nSecond line'
        checkbox = control(page, "checkbox")
        slider = control(page, "slider")
        password = control(page, "password")
        assert password["password"] is True and password["value"] is None, password
        assert "fixture-only-secret" not in json.dumps(page)

        def action(row: dict[str, Json], operation: str, text: str = "") -> Act:
            identity = row["id"]
            assert isinstance(identity, str)
            return Act(handle, identity, operation, text)

        results = batch(
            tmp_path,
            [
                action(editor, "set_value", value),
                action(editor, "read"),
                action(button, "invoke"),
                action(checkbox, "toggle"),
                action(slider, "set_range", "65"),
                action(control(page, "beta"), "select"),
                action(control(page, "choices"), "expand"),
                action(control(page, "choices"), "collapse"),
                action(password, "read"),
                action(control(page, "disabled"), "invoke"),
                action({"id": "42.2147483647.2147483646"}, "invoke"),
                Inspect(handle, limit=2, depth=10, offset=0),
                Inspect(handle, limit=2, depth=10, offset=2),
                # Exceed both the text and encoded-JSON caps without asking WPF to
                # lay out 10,000 lines. The earlier value retains multiline/UTF-8.
                action(editor, "set_value", '"' * 12001),
                action(editor, "read"),
                Inspect(handle, limit=100, depth=10, offset=0),
            ],
        )
        assert [ok for ok, _text in results] == [True] * 8 + [False] * 3 + [True] * 5, results
        assert decoded(results[1][1])["text"] == value
        selected = decoded(results[5][1])["control"]
        assert isinstance(selected, dict) and selected["value"] is True
        for index, expected in ((6, "Expanded"), (7, "Collapsed")):
            changed = decoded(results[index][1])["control"]
            assert isinstance(changed, dict) and changed["value"] == expected
        for index, expected in ((8, "Unsupported action"), (9, "disabled"), (10, "changed or disappeared")):
            assert expected in results[index][1]
        first, second = decoded(results[11][1]), decoded(results[12][1])
        assert first["next_offset"] == 2
        assert {str(row["id"]) for row in controls(first)}.isdisjoint(str(row["id"]) for row in controls(second))
        long_read = results[14][1]
        bounded = decoded(long_read)
        assert len(long_read) <= 18000 and bounded["truncated"] is True
        text = bounded["text"]
        assert isinstance(text, str) and 0 < len(text) < 12000 and text == '"' * len(text)
        # A fresh tree read must see the effects of actions made with the first
        # process's control IDs; no AutomationElement instances are shared.
        after = decoded(results[15][1])
        assert control(after, "status")["name"] == "Pressed 1"
        assert control(after, "checkbox")["value"] == "On"
        slider_value = control(after, "slider")["value"]
        assert isinstance(slider_value, dict) and slider_value["value"] == 65
