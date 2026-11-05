"""Our save/recheck and preview wiring on the native development runtime."""

import importlib.util
import os
import shutil
import subprocess
import sys
import time
import unittest
import uuid
from pathlib import Path

from automation.json_value import Json
from tests.json_fixture import json_object, json_value

if sys.platform != "win32":
    raise unittest.SkipTest("Native development tools")

lazy import shiboken6
lazy from PySide6.QtCore import Qt
lazy from PySide6.QtTest import QTest

from desktop_ui.island_model import Key
from desktop_ui.island_motion import settled
from desktop_ui.qt_runtime import prepare
from scripts.preview import Files, Preview
from tests.check_fixture import copy_check_scripts
from tests.git_fixture import initialized

prepare()

ROOT = Path(__file__).resolve().parent.parent


def wait_for(path: Path, condition: str, process: subprocess.Popen[bytes]) -> dict[str, Json]:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise AssertionError("Watch exited before " + condition)
        if path.exists():
            try:
                record = json_object(path.read_text())
            except OSError, ValueError:
                pass
            else:
                return record
        time.sleep(0.05)
    raise AssertionError("Watch never published " + condition)


def write_watch_source(root: Path, output: Path) -> None:
    copy_check_scripts(root, ("watch.py", "check.py"))
    shutil.copyfile(ROOT / "runtime.py", root / "runtime.py")
    (root / "pyproject.toml").write_text('[tool.workspace.architecture]\n[tool.ruff]\ntarget-version="py315"\n[tool.ruff.lint.pylint]\nmax-args=5\n')
    (root / ".gitignore").write_text("__pycache__/\n.ruff_cache/\n")
    (root / "requirements").mkdir()
    # Source-only keeper snapshots omit dotfiles; the fixture targets this runtime.
    (root / ".python-version").write_text(f"{sys.version_info.major}.{sys.version_info.minor}\n")
    for name in ("windows-py315.lock",):
        shutil.copyfile(ROOT / "requirements" / name, root / "requirements" / name)
    (root / "value.py").write_text("value = 1\n")
    tests = root / "tests"
    tests.mkdir()
    (tests / "__init__.py").write_text("")
    (tests / "test_value.py").write_text(
        "import json\nfrom pathlib import Path\nfrom value import value\n"
        "def test_current():\n"
        f"    output = Path({str(output)!r})\n"
        '    output.write_text(json.dumps({"value": value}))\n'
        '    assert value != 2, "an intentional failed edit"\n'
    )
    initialized(root)


def test_watch_rechecks_fresh_source_and_retains_baseline_after_failed_edits(tmp_path: Path) -> None:
    # Detect stale imported values in a reused test process, missed save events,
    # or a failed check advancing the session baseline instead of retrying it.
    if importlib.util.find_spec("watchdog") is None or importlib.util.find_spec("ruff") is None:
        raise unittest.SkipTest("Watchdog/Ruff are development-only dependencies.")
    root, output = tmp_path / "source", tmp_path / "observed.json"
    write_watch_source(root, output)
    stop = tmp_path / "stop"
    log = tmp_path / "watch.log"
    with (
        log.open("wb") as stream,
        subprocess.Popen(
            (sys.executable, "-B", "-m", "scripts.watch", "--tests", "tests/test_value.py", "--stop-file", str(stop)),
            cwd=root,
            stdout=stream,
            stderr=stream,
        ) as process,
    ):
        try:
            assert wait_for(output, "initial source", process)["value"] == 1
            deadline = time.monotonic() + 10
            while "Watching " not in log.read_text() and time.monotonic() < deadline:
                time.sleep(0.05)
            text = log.read_text()
            assert "Session receipt: " in text, text
            receipt = Path(text.split("Session receipt: ", 1)[1].splitlines()[0])
            original = receipt.read_bytes()
            output.unlink()
            (root / "value.py").write_text("value = 2\n")
            assert wait_for(output, "failed edit", process)["value"] == 2
            deadline = time.monotonic() + 10
            while "keeping the last successful baseline" not in log.read_text() and time.monotonic() < deadline:
                time.sleep(0.05)
            assert receipt.read_bytes() == original
            output.unlink()
            (root / "value.py").write_text("value = 3\n")
            assert wait_for(output, "corrected source", process)["value"] == 3
            deadline = time.monotonic() + 10
            while log.read_text().count("Watch baseline advanced.") < 2 and time.monotonic() < deadline:
                time.sleep(0.05)
            assert receipt.read_bytes() != original and "0 failed" in log.read_text()
        except Exception as error:
            raise AssertionError(log.read_text()) from error
        finally:
            stop.touch()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.wait(timeout=5)
        assert int(process.returncode or 0) == 0, log.read_text()


def test_native_check_reviews_source_once_across_desktop_handoff(tmp_path: Path) -> None:
    # A desktop relaunch must not repeat the coordinator's complete policy scan.
    # The single reviewed snapshot must still bind the successful native result.
    if importlib.util.find_spec("ruff") is None or shutil.which("git") is None:
        raise unittest.SkipTest("The editing coordinator needs development-only Ruff and Git.")
    root, output = tmp_path / "source", tmp_path / "observed.json"
    write_watch_source(root, output)
    for name in ("__init__.py", "desktop_session.py"):
        shutil.copyfile(ROOT / "tests" / name, root / "tests" / name)
    (root / "tests" / "test_value.py").rename(root / "tests" / "test_windows_value.py")
    # Two portable modules run in the main runner, which must exit before the
    # native lane starts. A re-executed runner would recursively launch checks
    # or append twice.
    markers = tuple(tmp_path / (name + ".ran") for name in ("test_commands", "test_llm"))
    for marker in markers:
        (root / "tests" / (marker.stem + ".py")).write_text(
            "import atexit\nfrom pathlib import Path\n"
            f'atexit.register(Path({str(marker.with_suffix(".exited"))!r}).write_text, "closed")\n'
            "def test_worker():\n"
            f'    with Path({str(marker)!r}).open("a") as output:\n'
            '        output.write("ran\\n")\n'
        )
    native = root / "tests" / "test_windows_value.py"
    exited = tuple(str(marker.with_suffix(".exited")) for marker in markers)
    native.write_text(native.read_text() + f'    assert all(Path(name).read_text() == "closed" for name in {exited!r})\n')
    receipt = tmp_path / "checked.json"
    checked = subprocess.run(
        (sys.executable, "-B", "-m", "scripts.check", "--full", "--native", "--receipt", str(receipt)),
        cwd=root,
        # Preserve the activated bundle's tools for nested check subprocesses.
        env=dict(os.environ, PYTHONPATH=os.pathsep.join((str(ROOT), *sys.path)), WORKSPACE_TEST_DESKTOP="workspace-tests-" + uuid.uuid4().hex),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=45,
        check=False,
    )
    assert checked.returncode == 0, checked.stdout + checked.stderr
    assert checked.stdout.count("Architecture: ") == 1, checked.stdout
    assert json_value(output.read_text()) == {"value": 1}
    assert all(marker.read_text() == "ran\n" for marker in markers)
    result: object = json_value(receipt.read_text())
    match result:
        case {"kind": "workspace-edit-check-v1", "passed": 3, "skipped": 0}:
            pass
        case _:
            raise AssertionError("The native result did not bind a successful source receipt")


def test_preview_uses_real_views_without_starting_native_services_and_closes_cleanly(tmp_path: Path) -> None:
    # Detect accidentally starting the production taskbar/hook/communication
    # services or failing to route sample-state changes to the real views.
    files = Files(tmp_path, tmp_path / "state.json")
    preview = Preview(files)
    try:
        assert preview.bar is not None
        assert preview.bar.controls is None and preview.bar.worker is None and preview.bar.audio_meter is None
        assert preview.bar.keys is None and not preview.bar.taskbar.ready
        assert preview.bar.notification_service is None
        assert preview.bar.status_service is None
        deadline = time.monotonic() + 5
        while not settled(preview.bar.motion) and time.monotonic() < deadline:
            QTest.qWait(20)
        island = preview.bar.window.capsules[Key.ISLAND]
        preview.selector.setCurrentIndex(2)
        preview.root.processEvents()
        assert "02:05" in island.accessibleName()
        assert preview.bar.ambient.text in preview.bar.window.capsules[Key.STATUS].accessibleName()
        assert preview.bar.ambient.text not in island.accessibleName()
        preview.selector.setCurrentIndex(5)
        preview.root.processEvents()
        assert "Transcribing" in island.accessibleName()
        preview.selector.setCurrentIndex(2)
        preview.root.processEvents()
        assert json_value(files.state.read_text()) == {"scenario": 2}
        assert preview.control.isVisible()
        assert preview.bar.window.windowTitle().startswith("Workspace preview")
        for name, label in (("Windows taskbar: Hidden", "Windows taskbar"), ("Windows notification settings", "Windows notification settings")):
            preview.bar.open_menu()
            row = next(cell for cell in preview.bar.window.capsules[Key.STATUS].cells if cell.accessibleName() == name)
            QTest.mouseClick(row, Qt.MouseButton.LeftButton)
            assert preview.status.text() == "Preview action: " + label
    finally:
        preview.close()
    preview.close()
    assert preview.bar.closed and not shiboken6.isValid(preview.control)
