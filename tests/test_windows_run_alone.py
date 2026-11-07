"""Each side runs without the other: the assistant with no desktop, the desktop with no assistant.

Each test runs one side's real `run` in a fresh interpreter. The imports below
are what those interpreters run, so a change to either side's composition
selects these tests.
"""

import os
import shutil
import subprocess
import sys
import textwrap
import time
import unittest
from pathlib import Path

if sys.platform != "win32":
    raise unittest.SkipTest("Windows process integration")

from assistant import app
from desktop_ui import desktop_app
from winapi.processes import ProcessJob

ROOT = Path(__file__).resolve().parent.parent
RUNS = (app.run, desktop_app.run)
"""What the fresh interpreters run; importing them here selects this module when either changes."""


def released(folder: Path) -> None:
    """Wait until the ended job's processes let go of `folder`: termination is asynchronous."""
    deadline = time.monotonic() + 10
    while True:
        try:
            shutil.rmtree(folder, ignore_errors=False)
        except FileNotFoundError:
            return
        except PermissionError:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.1)
        else:
            return


def run_alone(tmp_path: Path, *parts: str) -> str:
    """Run one side's `run` in a fresh interpreter, with a keeper state folder the other side never wrote to."""
    state = tmp_path / "state"
    state.mkdir()
    # The run's helpers (the shared browser host personal work samples through)
    # outlive it by design; the job ends them with the run, as a crash would.
    job = ProcessJob()
    try:
        with subprocess.Popen(
            [sys.executable, "-c", "".join(textwrap.dedent(part) for part in parts)],
            cwd=ROOT,
            env=dict(os.environ, PYTHONUTF8="1", LOCALAPPDATA=str(tmp_path), WORKSPACE_STATE=str(state), WORKSPACE_READY=str(state / "ready")),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        ) as process:
            job.add(process.pid)
            stdout, _ = process.communicate(timeout=90)
            code = process.returncode
    finally:
        job.close()
        released(tmp_path / "workspace" / "browser-connections")
    output = stdout.decode("utf-8", errors="replace")
    assert code == 0, f"Native exit {code & 0xFFFFFFFF:#x}: {output}"
    assert (state / "ready").exists(), output
    return output


CLOSE_WHEN_FOUND = """\
    import threading
    import time
    import uuid
    from components import Window
    from winapi import system, windows

    title = "Workspace alone " + uuid.uuid4().hex

    def close_when_found():
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if handle := windows.find(title):
                time.sleep(1.0)
                system.post_message(handle, system.WM_CLOSE, 0, 0)
                return
            time.sleep(0.05)

    threading.Thread(target=close_when_found, daemon=True).start()
"""


def test_the_assistant_runs_reports_ready_and_quits_with_no_desktop(tmp_path: Path) -> None:
    # Defect: the assistant needs the desktop to start (it waits for, imports or
    # builds UI), never reports ready to the keeper, or hangs on the keeper's close
    # while no desktop ever connected.
    output = run_alone(
        tmp_path,
        """\
        """,
        CLOSE_WHEN_FOUND,
        """\
        import sys
        from assistant import app
        from assistant.llm import Missing
        from assistant.state_store import windows_store
        from contracts.meeting_detection import PREFERENCE, AutomaticPreference
        from usage import DIRECTORY

        # Meeting detection's browser host outlives the assistant by design; this run checks only start and quit.
        windows_store(DIRECTORY / "automatic-meetings.bin", PREFERENCE).write(AutomaticPreference(enabled=False))

        assert app.run(Missing(()), window=Window(title, None), lock_name="Local" + chr(92) + title) is app.Exit.QUIT
        assert not any(name.startswith(("desktop_ui", "desktop.", "PySide6")) for name in sys.modules), "the assistant loaded the desktop"
        print("Assistant ran alone")
        """,
    )
    assert "Assistant ran alone" in output


def test_the_desktop_runs_reports_ready_and_quits_with_no_assistant(tmp_path: Path) -> None:
    # Defect: the desktop needs the assistant to start (it blocks on the link or
    # builds assistant owners), never reports ready to the keeper, or leaves Qt
    # running after the keeper's close.
    output = run_alone(
        tmp_path,
        """\
        """,
        CLOSE_WHEN_FOUND,
        """\
        import sys
        from desktop_ui import desktop_app
        from desktop_ui.desktop_bar import DesktopBar
        from desktop_ui.ui import Views
        from PySide6.QtWidgets import QApplication

        def headless_bar(actions, *, audio_level=None):
            # The real bar hosts the notification area; a second one would take its icons.
            return DesktopBar(actions, native_shell=False, audio_level=audio_level)

        desktop_app.run(window=Window(title, None), lock_name="Local" + chr(92) + title, views=Views(desktop=headless_bar))
        assert QApplication.instance() is None
        assert not any(name.startswith(("assistant", "automation")) for name in sys.modules), "the desktop loaded the assistant"
        print("Desktop ran alone")
        """,
    )
    assert "Desktop ran alone" in output
