"""End to end on Windows: Workspace changing itself. On a copy of Workspace, the
keeper installs a good change and the new code runs; undoes a change that crashes
on start; and refuses a change that fails its checks.

Starts the real workspace for a few minutes: `WORKSPACE_E2E=1 pytest tests/test_windows_self_change_e2e.py`.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

if sys.platform != "win32" or os.environ.get("WORKSPACE_E2E") != "1":
    raise unittest.SkipTest("end-to-end tests run on Windows, with WORKSPACE_E2E=1")

from assistant.workspace import Workspace
from keeper import copy_source
from keeper_control import Install, ask
from tests.fake_endpoint import fake_endpoint
from tests.test_windows_assistant_e2e import ROOT, both_ready, logs, wait_for, workspace
from winapi import windows


def keeper_log(home: Path) -> str:
    path = home / "workspace" / "keeper.log"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def change(live: Path, home: Path, summary: str, edit: str, old: str, *, new: str) -> None:
    """What the agent does: edit the workspace, then ask the keeper to install it."""
    workspace = Workspace(live, home / "workspace" / "workspace")
    workspace.reset()
    workspace.replace(edit, old, new)
    ask(home / "workspace" / "keeper" / "requests", Install(summary))


def no_review() -> None:
    assert windows.find("Workspace update review") is None, "Self-updates must not wait for approval by default."


def test_the_workspace_changes_itself_and_undoes_what_fails() -> None:
    home, live = Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp()) / "workspace"
    copy_source(ROOT, live)
    try:
        with fake_endpoint() as endpoint, workspace(endpoint, home, live):
            config = live / "config.py"

            # A good change: installed, and the programs restart with it.
            change(live, home, "a new snippet", "config.py", '",,thx": "Thanks!",', new='",,thx": "Thanks!",\n    ",,e2e": "end to end",')
            assert wait_for(lambda: '",,e2e"' in config.read_text(encoding="utf-8") and both_ready(home), no_review, 240), keeper_log(home)
            assert len(list((home / "workspace" / "versions").iterdir())) == 1  # the replaced version, kept
            assert wait_for(lambda: "on trial: a new snippet" in keeper_log(home), lambda: None, 60), keeper_log(home)

            # A change that passes its checks but crashes on start: undone by itself.
            main = live / "assistant" / "__main__.py"
            change(live, home, "a broken start", "assistant/__main__.py", "def main() -> None:\n", new="def main() -> None:\n    sys.exit(3)\n")
            assert wait_for(lambda: "Update undone: it didn't start." in keeper_log(home), no_review, 300), keeper_log(home)
            assert "sys.exit(3)" not in main.read_text(encoding="utf-8")
            assert wait_for(lambda: both_ready(home), lambda: None, 60), keeper_log(home)
            assert '",,e2e"' in config.read_text(encoding="utf-8")  # back to the good change, not further

            # A change that fails its checks: never installed.
            change(live, home, "a syntax error", "config.py", "APPS: Final", new="APPS Final")
            assert wait_for(lambda: "Not installed: the change failed its checks." in keeper_log(home), no_review, 300), keeper_log(home)
            assert "APPS: Final" in config.read_text(encoding="utf-8")
    except AssertionError:
        print(logs(home))
        raise
