"""Copied source uses the inherited SDK and Qt from the installed bundle."""

import os
import shutil
import subprocess
import sys
import textwrap
import time
import unittest
from dataclasses import replace
from pathlib import Path

if sys.platform != "win32":
    raise unittest.SkipTest("Windows bundle integration")

from components import ASSISTANT, Window
from keeper import Process, WindowsUser32
from runtime import activate

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


def test_copied_source_starts_the_sdk_and_qt_with_the_inherited_bundle(tmp_path: Path) -> None:
    if not (ROOT / ".runtime").is_dir() and not os.environ.get("WORKSPACE_BUNDLED_RUNTIME"):
        raise unittest.SkipTest("Windows bundle integration")
    activate()
    source = tmp_path / "source"
    # This owns copied production source binding, not keeper's complete mirror
    # policy. Keeper's tests cover that policy; docs/tests/tooling are not needed
    # to initialize the SDK and native UI in this fresh process.
    source.mkdir()

    def ignore_bytecode(_folder: str, names: list[str]) -> set[str]:
        return set(names) & {"__pycache__"}

    for package in ("assistant", "contracts", "desktop_ui", "automation", "gateway", "link", "miryoku", "winapi"):
        shutil.copytree(ROOT / package, source / package, ignore=ignore_bytecode)
    for module in ROOT.glob("*.py"):
        shutil.copyfile(module, source / module.name)
    assert not (source / ".runtime").exists() and not (source / ".python").exists()
    script = (
        "from runtime import activate; activate(); import assistant.sdk, desktop_ui.desktop_bar; "
        "from pathlib import Path; import os, runtime, PySide6; "
        "assert all(Path(module.__file__).is_relative_to(Path.cwd()) for module in (runtime, assistant.sdk, desktop_ui.desktop_bar)); "
        "assert Path(PySide6.__file__).is_relative_to(Path(os.environ['WORKSPACE_BUNDLED_RUNTIME'])); "
        "from desktop_ui.qt_ui import EventLoop, application; "
        "root=application(); "
        "loop=EventLoop(root, lambda: None); loop.pump(); loop.close(); root.processEvents(); print('Copied SDK and Qt passed')"
    )
    checked = subprocess.run(
        [sys.executable, "-S", "-c", script],
        cwd=source,
        env=dict(os.environ, PYTHONUTF8="1"),
        capture_output=True,
        timeout=75,
        check=False,
    )
    assert checked.returncode == 0, (checked.stdout + checked.stderr).decode("utf-8", errors="replace")
    assert b"Copied SDK and Qt passed" in checked.stdout


def test_qt_import_keeps_asyncio_workers_usable_in_a_fresh_interpreter() -> None:
    activate()
    script = (
        "from runtime import activate; activate(); import asyncio; "
        "import desktop_ui.components.text; "
        "assert asyncio.run(asyncio.to_thread(lambda: 42)) == 42; print('Qt and async workers passed')"
    )
    checked = subprocess.run(
        [sys.executable, "-S", "-c", script],
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
    activate()
    script = (
        "from runtime import activate; activate(); "
        "import desktop_ui.components.canvas_chrome; from pydantic import Field; "
        "import desktop_ui.ui_spec; desktop_ui.ui_spec.bar_specs(); print('Qt then specs passed')"
    )
    checked = subprocess.run(
        [sys.executable, "-S", "-c", script],
        cwd=ROOT,
        env=dict(os.environ, PYTHONUTF8="1"),
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert checked.returncode == 0, (checked.stdout + checked.stderr).decode("utf-8", errors="replace")
    assert b"Qt then specs passed" in checked.stdout


def run_alone(tmp_path: Path, *parts: str) -> str:
    """Run one side's `run` in a fresh interpreter, with a keeper state folder the other side never wrote to."""
    state = tmp_path / "state"
    state.mkdir()
    checked = subprocess.run(
        [sys.executable, "-S", "-c", "".join(textwrap.dedent(part) for part in parts)],
        cwd=ROOT,
        env=dict(os.environ, PYTHONUTF8="1", LOCALAPPDATA=str(tmp_path), WORKSPACE_STATE=str(state), WORKSPACE_READY=str(state / "ready")),
        capture_output=True,
        timeout=90,
        check=False,
    )
    output = (checked.stdout + checked.stderr).decode("utf-8", errors="replace")
    assert checked.returncode == 0, f"Native exit {checked.returncode & 0xFFFFFFFF:#x}: {output}"
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
        from runtime import activate
        activate()
        """,
        CLOSE_WHEN_FOUND,
        """\
        import sys
        from assistant import app
        from assistant.llm import Missing

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
        from runtime import activate
        activate()
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
