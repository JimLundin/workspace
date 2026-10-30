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
from scripts.deploy_processes import inventory

ROOT = Path(__file__).resolve().parent.parent


def test_keeper_allows_owned_cleanup_longer_than_five_seconds(tmp_path: Path) -> None:
    # Defect: the keeper kills a responsive assistant/automation child while
    # its legitimate cleanup is still running, blocking checked deployment.
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
            assert process.returncode == 0, "The keeper terminated a responsive child before cleanup finished"
        finally:
            if process.poll() is None:
                if handle := boundary.FindWindowW(None, title):
                    boundary.PostMessageW(handle, 0x0010, 0, 0)
                process.wait(timeout=15)


def test_shared_installed_python_processes_are_bound_to_workspace_ownership(tmp_path: Path) -> None:
    # Detect missing native children after removing .python, or including an
    # unrelated process that happens to use the same installed interpreter.
    python = Path(sys.base_prefix) / "pythonw.exe"
    stop = tmp_path / "stop"
    ready = tmp_path / "ready"
    wait = "from pathlib import Path; import time\nwhile not Path('stop').exists(): time.sleep(0.01)\n"
    (tmp_path / "child_fixture.py").write_text(wait)
    script = tmp_path / "workspace.pyw"
    script.write_text(
        "from pathlib import Path; import subprocess,sys\n"
        "child=subprocess.Popen([sys.executable,'-m','child_fixture'])\n"
        "Path('ready.tmp').write_text(str(child.pid)); Path('ready.tmp').replace('ready')\nchild.wait()\n"
    )
    with (
        subprocess.Popen([str(python), str(script)], cwd=tmp_path) as parent,
        subprocess.Popen([str(python), "-c", wait, str(script)], cwd=tmp_path) as unrelated,
    ):
        try:
            deadline = time.monotonic() + 10
            while not ready.is_file():
                if time.monotonic() >= deadline:
                    raise AssertionError("The installed-interpreter fixture did not start")
                time.sleep(0.01)
            child = int(ready.read_text())
            rows = inventory(tmp_path)
            assert {row.pid for row in rows} == {parent.pid, child}
            assert unrelated.pid not in {row.pid for row in rows}
            assert all(Path(row.executable) == python for row in rows)
        finally:
            stop.write_text("stop")
            parent.wait(timeout=10)
            unrelated.wait(timeout=10)


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

    for package in ("assistant", "automation", "miryoku", "winapi"):
        shutil.copytree(ROOT / package, source / package, ignore=ignore_bytecode)
    for module in ROOT.glob("*.py"):
        shutil.copyfile(module, source / module.name)
    assert not (source / ".runtime").exists() and not (source / ".python").exists()
    script = (
        "from runtime import activate; activate(); import assistant.sdk, assistant.agent_toasts; "
        "from pathlib import Path; import os, runtime, PySide6; "
        "assert all(Path(module.__file__).is_relative_to(Path.cwd()) for module in (runtime, assistant.sdk, assistant.agent_toasts)); "
        "assert Path(PySide6.__file__).is_relative_to(Path(os.environ['WORKSPACE_BUNDLED_RUNTIME'])); "
        "from assistant.qt_ui import EventLoop, application; "
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
        "import assistant.ui_components.text; "
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


def test_work_window_closes_with_its_ui_owner_in_a_fresh_process(tmp_path: Path) -> None:
    script = textwrap.dedent("""\
        import faulthandler
        import threading
        from runtime import activate
        activate()
        from assistant.qt_runtime import prepare
        prepare()
        from PySide6.QtWidgets import QApplication
        from assistant.qt_ui import later
        from assistant.ui import Ui
        from assistant.work_canvas import WorkCanvas
        from usage import DIRECTORY

        faulthandler.enable()

        class OffscreenUi(Ui):
            __slots__ = ()

            def _create_work(self, work):
                view = super()._create_work(work)
                view.window.move(-4000, -3000)
                return view

        ui = OffscreenUi()
        ui.configure_canvas(WorkCanvas(DIRECTORY / "work" / "canvas.sqlite3", lambda run: None, autonomous=False), lambda title, target: None)
        failures = []
        owners = []

        def control():
            try:
                work = ui.work(lambda command: None, focus=False)
                ready = threading.Event()
                def opened(root):
                    owners.append(threading.current_thread() is threading.main_thread())
                    later(root, 40, ready.set)
                ui.post(opened)
                assert ready.wait(10), "Work did not open on the UI thread"
                ui.close_work()
                assert work.closed_ready.is_set(), "Work did not acknowledge closing"
            except BaseException as error:
                failures.append(error)
            finally:
                ui.close()

        controller = threading.Thread(target=control, name="test application control")
        controller.start()
        ui.run()
        controller.join(timeout=10)
        assert not controller.is_alive(), "Application control did not close"
        assert not failures, failures
        assert owners == [True], "Qt widgets were created outside the main thread"
        assert QApplication.instance() is None, "The UI application remained alive"
        print("Work and UI owner closed")
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
    assert "Work and UI owner closed" in output


def _native_controller_lifetime(tmp_path: Path, *, qt_first: bool) -> None:
    script = textwrap.dedent("""\
        import faulthandler
        import sys
        import threading
        import uuid
        from runtime import activate
        activate()
        from assistant import app
        from assistant.llm import Missing
        from assistant.qt_runtime import prepare
        prepare()
        from PySide6.QtWidgets import QApplication
        from assistant.ui import Ui
        from assistant.work_canvas import WorkCanvas
        from usage import DIRECTORY
        from winapi import shell, system

        faulthandler.enable()
        title = "Workspace controller lifetime " + uuid.uuid4().hex
        observed = []

        class OffscreenUi(Ui):
            __slots__ = ()

            def _create_work(self, work):
                view = super()._create_work(work)
                view.window.move(-4000, -3000)
                return view

        class Controller:
            __slots__ = ("owner", "ui", "window")

            def __init__(self, settings, ui):
                self.owner = threading.get_ident()
                assert self.owner != threading.main_thread().ident
                self.ui = ui
                self.window = shell.AppWindow(title, self.message)

            def run(self):
                self.ui.agent(None, lambda: None, reveal=False)
                canvas = WorkCanvas(DIRECTORY / "work" / "canvas.sqlite3", lambda run: None, autonomous=False)
                self.ui.configure_canvas(canvas, lambda title, target: None)
                self.ui.work(lambda command: None, focus=False)
                self.ui.post(self.ready)
                system.run_message_loop()

            def ready(self, root):
                observed.append(("qt", threading.current_thread() is threading.main_thread()))
                if sys.argv[1] == "qt-first":
                    root.quit()
                else:
                    assert system.post_message(self.window.handle, system.WM_CLOSE, 0, 0)

            def message(self, hwnd, message, wparam, lparam):
                if message == system.WM_CLOSE:
                    observed.append(("control", threading.get_ident() == self.owner))
                    self.ui.close_desktop()
                    self.ui.close_agent()
                    self.ui.close_work()
                    self.ui.close()
                    self.window.destroy()
                    system.post_quit()
                    return 0
                return None

        runtime = app.Runtime(title, "Local" + chr(92) + title, OffscreenUi, Controller)
        assert app.run(Missing(()), runtime=runtime) is app.Exit.QUIT
        assert observed == [("qt", True), ("control", True)], observed
        assert QApplication.instance() is None
        assert not any(thread.name == "assistant control" for thread in threading.enumerate())
        print("Native controller and Qt closed")
        """)
    checked = subprocess.run(
        [sys.executable, "-S", "-c", script, "qt-first" if qt_first else "controller-first"],
        cwd=ROOT,
        env=dict(os.environ, PYTHONUTF8="1", LOCALAPPDATA=str(tmp_path)),
        capture_output=True,
        timeout=60,
        check=False,
    )
    output = (checked.stdout + checked.stderr).decode("utf-8", errors="replace")
    assert checked.returncode == 0, f"Native exit {checked.returncode & 0xFFFFFFFF:#x}: {output}"
    assert "Native controller and Qt closed" in output


def test_native_controller_messages_and_qt_share_a_clean_process_lifetime(tmp_path: Path) -> None:
    _native_controller_lifetime(tmp_path, qt_first=False)


def test_qt_exit_first_still_closes_the_native_controller(tmp_path: Path) -> None:
    _native_controller_lifetime(tmp_path, qt_first=True)


def test_controller_initialization_failure_closes_qt_and_propagates(tmp_path: Path) -> None:
    script = textwrap.dedent("""\
        import threading
        import uuid
        from runtime import activate
        activate()
        from assistant import app
        from assistant.llm import Missing
        from assistant.qt_runtime import prepare
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


def test_shutdown_resolves_pending_and_late_ui_requests(tmp_path: Path) -> None:
    script = textwrap.dedent("""\
        import threading
        from runtime import activate
        activate()
        from assistant.ui import Ui
        from assistant.qt_runtime import prepare
        prepare()
        from PySide6 import QtWidgets
        from PySide6.QtCore import Qt
        from assistant.qt_ui import later

        class OffscreenPresentation:
            def position(self, dialog, width, height):
                dialog.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
                dialog.setWindowFlag(Qt.WindowType.WindowDoesNotAcceptFocus)
                dialog.setGeometry(-4000, -3000, width, height)

            def reveal(self, window, focus):
                pass

        ui = Ui(presentation=OffscreenPresentation())
        answers = []
        failures = []

        def close_pending(root, attempts=0):
            if any(isinstance(window, QtWidgets.QInputDialog) for window in root.topLevelWidgets()):
                root.quit()
            elif attempts < 100:
                later(root, 10, lambda: close_pending(root, attempts + 1))
            else:
                failures.append("The pending prompt never appeared")
                root.quit()

        def control():
            try:
                answers.append(ui.prompt("Isolated shutdown check"))
                ui.close()
                answers.append(ui.prompt("Already closed"))
                from winapi.shapes import Rect
                assert ui.choose_region(Rect(0, 0, 100, 100)) is None
                try:
                    ui.answer("Already closed", lambda text: None)
                except OSError:
                    pass
                else:
                    raise AssertionError("A closed UI must reject window creation")
            except BaseException as error:
                failures.append(error)

        controller = threading.Thread(target=control, name="pending UI request", daemon=True)
        controller.start()
        ui.post(close_pending)
        ui.run()
        controller.join(timeout=10)
        assert not controller.is_alive(), "Shutdown left an input caller waiting"
        assert not failures, failures
        assert answers == [None, None], answers
        print("Pending and late UI requests resolved")
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
    assert "Pending and late UI requests resolved" in output
