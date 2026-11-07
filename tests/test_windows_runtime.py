"""Copied source uses the inherited SDK and Qt from the installed bundle."""

import os
import subprocess
import sys
import time
import unittest
from dataclasses import replace
from pathlib import Path

if sys.platform != "win32":
    raise unittest.SkipTest("Windows bundle integration")

from components import ASSISTANT, Window
from keeper import Process, WindowsUser32

ROOT = Path(__file__).resolve().parent.parent


def test_keeper_allows_owned_cleanup_longer_than_five_seconds(tmp_path: Path) -> None:
    # Defect: the keeper kills a responsive assistant while its legitimate
    # cleanup is still running.
    ready = tmp_path / "ready"
    title = "workspace delayed cleanup " + tmp_path.name
    script = tmp_path / "cleanup_child.py"
    script.write_text(
        "from pathlib import Path\n"
        "import time\n"
        "from winapi import windows, system\n"
        f"title = {title!r}\n"
        "hwnd = windows.create_hidden(title)\n"
        f"Path({str(ready)!r}).touch()\n"
        "for message in system.messages():\n"
        "    if message.hwnd == hwnd and message.message == system.WM_CLOSE:\n"
        "        time.sleep(6)\n"
        "        break\n"
        "windows.destroy(hwnd)\n",
        encoding="utf-8",
    )
    with subprocess.Popen([sys.executable, str(script)], env={**os.environ, "PYTHONPATH": str(ROOT)}) as process:
        boundary = WindowsUser32()
        try:
            deadline = time.monotonic() + 15
            while not ready.exists():
                if process.poll() is not None or time.monotonic() >= deadline:
                    raise AssertionError("The cleanup fixture did not become ready")
                time.sleep(0.01)
            child = Process(process, replace(ASSISTANT, window=Window(title, None)), boundary)
            child.stop()
            assert process.poll() == 0, "The keeper terminated a responsive child before cleanup finished"
        finally:
            if process.poll() is None:
                if handle := boundary.FindWindowW(None, title):
                    boundary.PostMessageW(handle, 0x0010, 0, 0)
                process.wait(timeout=15)


def test_qt_import_keeps_asyncio_workers_usable_in_a_fresh_interpreter() -> None:
    script = (
        "import asyncio; "
        "import desktop_ui.components.text; "
        "assert asyncio.run(asyncio.to_thread(lambda: 42)) == 42; print('Qt and async workers passed')"
    )
    checked = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env=dict(os.environ, PYTHONUTF8="1"),
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert checked.returncode == 0, (checked.stdout + checked.stderr).decode("utf-8", errors="replace")
    assert b"Qt and async workers passed" in checked.stdout


def test_specs_validate_after_qt_loads_in_a_fresh_interpreter() -> None:
    # Defect: a desktop module that loads Qt before pydantic's lazily exported
    # names fails to import (PySide's import hook re-enters pydantic mid-load),
    # so an install whose changed modules import in that order is refused.
    script = (
        "import desktop_ui.components.canvas_chrome; from pydantic import Field; "
        "import desktop_ui.ui_spec; desktop_ui.ui_spec.bar_specs(); print('Qt then specs passed')"
    )
    checked = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env=dict(os.environ, PYTHONUTF8="1"),
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert checked.returncode == 0, (checked.stdout + checked.stderr).decode("utf-8", errors="replace")
    assert b"Qt then specs passed" in checked.stdout
