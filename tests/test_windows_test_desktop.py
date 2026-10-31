"""Our fixture bootstrap must contain real Qt windows and native children."""

import ctypes
import os
import subprocess
import sys
import unittest
import uuid
from pathlib import Path

from pydantic import TypeAdapter

if sys.platform != "win32":
    raise unittest.SkipTest("Windows test desktop ownership")

from win32more.Windows.Win32.System.StationsAndDesktops import (
    CloseDesktop,
    GetThreadDesktop,
    GetUserObjectInformationW,
    OpenInputDesktop,
)
from win32more.Windows.Win32.System.Threading import GetCurrentThreadId
from win32more.Windows.Win32.UI.WindowsAndMessaging import GetWindowThreadProcessId

from tests.test_windows_agent_toasts import notifications
from tests.test_windows_computer import fixture
from winapi import windows


def desktop_name(thread: int) -> str:
    handle = GetThreadDesktop(thread)
    assert handle is not None
    return object_name(handle)


def object_name(handle: int) -> str:
    buffer = ctypes.create_unicode_buffer(256)
    assert GetUserObjectInformationW(handle, 2, ctypes.addressof(buffer), ctypes.sizeof(buffer), None)
    return buffer.value


def test_qt_and_accessibility_children_stay_off_the_input_desktop(tmp_path: Path) -> None:
    # Defects: test package initialization attaches too late, a child escapes
    # to the input desktop, or each Python child chooses a disconnected desktop.
    # Exercise our real fixture owners; no assertions about library algorithms.
    expected = os.environ["WORKSPACE_TEST_DESKTOP"]
    assert desktop_name(GetCurrentThreadId()) == expected
    input_desktop = OpenInputDesktop(0, 0, 1)
    if input_desktop is None:
        raise unittest.SkipTest("Input desktop cannot be observed while locked")
    try:
        before = object_name(input_desktop)
        assert expected != before, "Native test fixtures were attached to the user's desktop"
        with notifications() as panel, fixture(tmp_path) as accessibility:
            panel.agent.say("Isolated native fixture")
            panel.pump()
            card = next(iter(panel.view.cards.values()))
            for handle in (card.handle, accessibility):
                assert windows.is_visible(handle), "Isolation hid the fixture instead of exercising native presentation"
                assert desktop_name(GetWindowThreadProcessId(handle, None)) == expected
        assert object_name(input_desktop) == before, "Tests switched the input desktop"
    finally:
        assert CloseDesktop(input_desktop)


def test_desktop_bootstrap_preserves_arguments_streams_and_failure_status(tmp_path: Path) -> None:
    # Defects: relaunch drops interpreter/script arguments, inherits unusable
    # streams, consumes input in the parent, reports success for child failure,
    # or lets an inherited E2E opt-in bypass ordinary check isolation.
    script = tmp_path / "native-bootstrap.py"
    script.write_text(
        "import json, os, sys\nfrom pathlib import Path\n"
        "from runtime import activate\nactivate()\n"
        "from scripts.check import execute\nfrom scripts.check_results import Selection\n"
        "execute(Selection((), (), 'explicit iteration scope'), Path.cwd())\n"
        "from scripts.native_desktop import current_name\n"
        "assert current_name() == os.environ['WORKSPACE_TEST_DESKTOP']\n"
        "assert sys.stdin.read() == 'Fixture input Åäö\\n'\n"
        "print(json.dumps(sys.argv[1:], ensure_ascii=False))\n"
        "print('Fixture failure Åäö', file=sys.stderr)\nraise SystemExit(7)\n",
        encoding="utf-8",
    )
    # Request a fresh desktop identity to force relaunch even though this child
    # initially inherits our private desktop. Neither desktop is ever shown.
    arguments = ('spaces and "quotes"', "Åäö $literal `value`")
    checked = subprocess.run(
        (sys.executable, "-X", "utf8", "-B", str(script), *arguments),
        cwd=Path(__file__).resolve().parent.parent,
        input="Fixture input Åäö\n",
        env=dict(
            os.environ,
            PYTHONPATH=str(Path(__file__).resolve().parent.parent),
            WORKSPACE_TEST_DESKTOP="workspace-tests-" + uuid.uuid4().hex,
            WORKSPACE_E2E="1",
        ),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )
    assert checked.returncode == 7, checked.stderr
    assert TypeAdapter[tuple[str, ...]](tuple[str, ...]).validate_json(checked.stdout) == arguments
    assert checked.stderr.strip() == "Fixture failure Åäö"
