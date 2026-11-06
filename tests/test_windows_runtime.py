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

    for package in ("assistant", "contracts", "desktop_ui", "automation", "gateway", "miryoku", "winapi"):
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


def test_native_controller_messages_and_qt_share_a_clean_process_lifetime(tmp_path: Path) -> None:
    script = textwrap.dedent("""\
        import faulthandler
        import threading
        import uuid
        from runtime import activate
        activate()
        from assistant import app
        from assistant.llm import Missing
        from desktop_ui.qt_runtime import prepare
        prepare()
        from PySide6.QtWidgets import QApplication
        from desktop_ui.ui import Ui, Views
        from assistant.work_canvas import WorkCanvas
        from desktop_ui.work_canvas_window import CanvasWindow
        from usage import DIRECTORY
        from winapi import shell, system

        faulthandler.enable()
        title = "Workspace controller lifetime " + uuid.uuid4().hex
        observed = []

        def offscreen_canvas(root, work, canvas):
            view = CanvasWindow(root, work, canvas)
            view.window.move(-4000, -3000)
            return view

        def offscreen_ui():
            return Ui(views=Views(canvas=offscreen_canvas))

        class Controller:
            __slots__ = ("owner", "ui", "window")

            def __init__(self, settings, ui):
                self.owner = threading.get_ident()
                assert self.owner != threading.main_thread().ident
                self.ui = ui
                self.window = shell.AppWindow(title, self.message)

            def run(self):
                self.ui.agent(lambda: None, reveal=False)
                canvas = WorkCanvas(DIRECTORY / "work" / "canvas.sqlite3", lambda run: None, self.ui.publish_canvas, autonomous=False)
                self.ui.configure_canvas(canvas, lambda title, target: None, observe_session=canvas.observe_session)
                self.ui.configure_work(lambda command: None)
                self.ui.work_window().show(focus=False)
                self.ui.post(self.ready)
                system.run_message_loop()

            def ready(self, root):
                observed.append(("qt", threading.current_thread() is threading.main_thread()))
                assert system.post_message(self.window.handle, system.WM_CLOSE, 0, 0)

            def message(self, hwnd, message, wparam, lparam):
                if message == system.WM_CLOSE:
                    observed.append(("control", threading.get_ident() == self.owner))
                    self.ui.close_desktop()
                    self.ui.close_windows()
                    self.ui.close()
                    self.window.destroy()
                    system.post_quit()
                    return 0
                return None

        runtime = app.Runtime(title, "Local" + chr(92) + title, offscreen_ui, Controller)
        assert app.run(Missing(()), runtime=runtime) is app.Exit.QUIT
        assert observed == [("qt", True), ("control", True)], observed
        assert QApplication.instance() is None
        assert not any(thread.name == "assistant control" for thread in threading.enumerate())
        print("Native controller and Qt closed")
        """)
    checked = subprocess.run(
        [sys.executable, "-S", "-c", script],
        cwd=ROOT,
        env=dict(os.environ, PYTHONUTF8="1", LOCALAPPDATA=str(tmp_path)),
        capture_output=True,
        timeout=60,
        check=False,
    )
    output = (checked.stdout + checked.stderr).decode("utf-8", errors="replace")
    assert checked.returncode == 0, f"Native exit {checked.returncode & 0xFFFFFFFF:#x}: {output}"
    assert "Native controller and Qt closed" in output


def test_controller_initialization_failure_closes_qt_and_propagates(tmp_path: Path) -> None:
    script = textwrap.dedent("""\
        import threading
        import uuid
        from runtime import activate
        activate()
        from assistant import app
        from assistant.llm import Missing
        from desktop_ui.qt_runtime import prepare
        prepare()
        from PySide6.QtWidgets import QApplication

        title = "Workspace startup failure " + uuid.uuid4().hex
        def fail(settings, ui):
            raise RuntimeError("Fixture startup failed")

        runtime = app.Runtime(title=title, lock_name="Local" + chr(92) + title, controller=fail)
        try:
            app.run(Missing(()), runtime=runtime)
        except RuntimeError as error:
            assert str(error) == "Fixture startup failed"
        else:
            raise AssertionError("The controller startup failure was lost")
        assert QApplication.instance() is None
        assert not any(thread.name == "assistant control" for thread in threading.enumerate())
        print("Controller failure closed Qt")
        """)
    checked = subprocess.run(
        [sys.executable, "-S", "-c", script],
        cwd=ROOT,
        env=dict(os.environ, PYTHONUTF8="1", LOCALAPPDATA=str(tmp_path)),
        capture_output=True,
        timeout=60,
        check=False,
    )
    output = (checked.stdout + checked.stderr).decode("utf-8", errors="replace")
    assert checked.returncode == 0, f"Native exit {checked.returncode & 0xFFFFFFFF:#x}: {output}"
    assert "Controller failure closed Qt" in output
