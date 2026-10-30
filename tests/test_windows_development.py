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

from scripts.install_inbox_hooks import configuration
from tests.json_fixture import json_value

if sys.platform != "win32":
    raise unittest.SkipTest("Native development tools")

lazy import shiboken6

from assistant.qt_runtime import prepare
from scripts.preview import Files, Preview
from tests.test_quality import migrations

prepare()

ROOT = Path(__file__).resolve().parent.parent


def wait_for(path: Path, condition: str, process: subprocess.Popen[bytes]) -> dict[str, object]:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise AssertionError("Watch exited before " + condition)
        if path.exists():
            try:
                record: dict[str, object] = configuration(json_value(path.read_text()))
            except OSError, ValueError:
                pass
            else:
                return record
        time.sleep(0.05)
    raise AssertionError("Watch never published " + condition)


def write_watch_source(root: Path, output: Path) -> None:
    scripts = root / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "__init__.py").write_text("")
    for name in (
        "watch.py",
        "check.py",
        "source_analysis.py",
        "architecture.py",
        "quality.py",
        "deploy_files.py",
        "development_paths.py",
        "check_native.py",
        "native_desktop.py",
    ):
        shutil.copyfile(ROOT / "scripts" / name, scripts / name)
    shutil.copyfile(ROOT / "runtime.py", root / "runtime.py")
    (root / "pyproject.toml").write_text(
        '[tool.workspace.architecture]\nmodels=[]\n[tool.ruff]\ntarget-version="py315"\n[tool.ruff.lint.pylint]\nmax-args=3\nmax-positional-args=5\n'
    )
    (root / ".gitignore").write_text("__pycache__/\n.ruff_cache/\n")
    (root / "requirements").mkdir()
    shutil.copyfile(ROOT / ".python-version", root / ".python-version")
    for name in ("windows-py315.lock",):
        shutil.copyfile(ROOT / "requirements" / name, root / "requirements" / name)
    migrations(root)
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
    subprocess.run(("git", "init", "--quiet", str(root)), check=True, capture_output=True)


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
    # Two registered portable modules exercise the real spawned-worker handoff.
    # A re-executed runner would recursively launch checks or append twice.
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
        env=dict(os.environ, PYTHONPATH=str(ROOT), WORKSPACE_TEST_DESKTOP="workspace-tests-" + uuid.uuid4().hex),
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
    preview = Preview("both", files)
    try:
        assert preview.bar is not None and preview.feed is not None
        assert preview.bar.controls is None and preview.bar.worker is None and preview.bar.audio_meter is None
        assert preview.bar.keys is None and not preview.bar.taskbar.ready
        assert preview.bar.notification_service is None
        assert preview.bar.weather_service is None and preview.bar.status_service is None
        preview.selector.setCurrentIndex(2)
        preview.root.processEvents()
        assert not preview.bar.record.text() and "02:05" in preview.bar.record.toolTip()
        assert preview.bar.ambient.clock in preview.bar.status.text() and preview.bar.ambient.text in preview.bar.status.toolTip()
        preview.selector.setCurrentIndex(5)
        preview.root.processEvents()
        assert not preview.bar.status.text() and preview.bar.status.processing
        preview.selector.setCurrentIndex(2)
        preview.root.processEvents()
        assert preview.feed.cards and json_value(files.state.read_text()) == {"scenario": 2}
        assert preview.control.isVisible()
        assert all(pill.windowTitle().startswith("Workspace preview") for pill in preview.bar.pills)
        preview.bar.open_menu()
        for action in preview.bar.menu.actions():
            if action.text() in ("Windows taskbar", "Windows notification settings"):
                action.trigger()
                assert preview.status.text() == "Preview action: " + action.text()
        preview.bar.menu.close()
    finally:
        preview.close()
    preview.close()
    assert preview.bar.closed and preview.feed.closed and not shiboken6.isValid(preview.control)
