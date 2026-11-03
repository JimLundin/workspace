"""Real archive/file boundaries for the source-only deployment path."""

import contextlib
import io
import os
import shutil
import subprocess
import sys
import unittest
import zipfile
from collections.abc import Generator
from pathlib import Path, PureWindowsPath

from scripts import deploy
from scripts.architecture import Report
from scripts.check import CheckRun, Options, publish_check
from scripts.check_results import Results, Selection
from scripts.deploy import installed_drift
from scripts.deploy_archive import repack
from scripts.deploy_files import (
    HELPERS,
    PINS,
    CheckedArchitecture,
    CheckReceipt,
    file_at,
    files,
    member,
    names,
    sha,
    source_map,
    write,
    write_receipt,
    zip_files,
)
from scripts.deploy_policy import ComponentRestart, FullRestart, Version, restart_plan
from scripts.deploy_processes import Observation, Process, installed_processes, role_for
from scripts.deploy_values import RUNTIME_AUDIT, Stopped
from scripts.deploy_windows import Release, drive, group, launch_interpreter
from scripts.development_paths import PYTHON
from tests.component_deploy_fixture import staged
from tests.git_fixture import initialized


def test_rollback_relaunches_the_observed_interpreter_while_checked_source_uses_installed_python() -> None:
    # Detect a restored old launcher handing off and invalidating keeper PID
    # readiness after a partial replacement failure.
    keeper = Process(10, 1, "keeper", r"C:\previous\pythonw.exe", 1)
    stopped: Stopped = {"was_running": True, "clean_exit": True, "processes_before": [keeper.identity()], "exits": []}
    assert launch_interpreter({"rolled_back": True}, stopped) == Path(keeper.executable)
    assert launch_interpreter({}, stopped) == PYTHON.with_name("pythonw.exe")
    stopped = {"was_running": True, "clean_exit": True, "processes_before": [], "exits": []}
    with unittest.TestCase().assertRaisesRegex(RuntimeError, "no observed keeper"):
        launch_interpreter({"rolled_back": True}, stopped)


def test_shared_interpreter_inventory_owns_only_installed_commands_and_their_descendants() -> None:
    # Detect stopping unrelated Python apps or losing module-launched children
    # when the executable is installed outside Workspace.
    live = PureWindowsPath(r"C:\installed\workspace")
    python = r"C:\Python315\pythonw.exe"
    keeper = Observation(Process(10, 1, "keeper", python, 1), (python, "-B", str(live / "workspace.pyw")))
    assistant = Observation(Process(11, 10, "assistant", python, 2), (python, "-m", "assistant"))
    grandchild = Observation(Process(12, 11, "runtime", python, 3), (python, "-c", "pass"))
    unrelated = Observation(Process(13, 1, "runtime", python, 4), (python, r"C:\elsewhere\tool.py", str(live / "workspace.pyw")))
    sibling = Observation(Process(14, 1, "keeper", python, 5), (python, r"C:\installed\workspace-other\workspace.pyw"))
    assert installed_processes((grandchild, unrelated, assistant, sibling, keeper), live) == (keeper.process, assistant.process, grandchild.process)
    assert installed_processes((assistant, unrelated, sibling), live) == ()


def test_restart_plan_tracks_shared_removed_and_package_dependencies(tmp_path: Path) -> None:
    # Detect selecting by directory alone, dropping consumers of removed imports,
    # failing to include extracted UI/package initialization in a child's lifetime,
    # or reading an unchanged module from the overlay that holds only replaced files.
    source = {
        "keeper.py": "import keeper_control\nimport supervisor_support\n",
        "keeper_control.py": "",
        "supervisor_support.py": "value = 1\n",
        "miryoku/__init__.py": "",
        "miryoku/__main__.py": "from miryoku import engine\n",
        "miryoku/engine.py": "import protocol\n",
        "assistant/__init__.py": "",
        "assistant/__main__.py": "from assistant import app\n",
        "assistant/app.py": "import protocol\nimport retired\nimport desktop_ui.ui\n",
        "desktop_ui/__init__.py": "",
        "desktop_ui/ui.py": "value = 1\n",
        "automation/__init__.py": "",
        "automation/__main__.py": "from automation import app\n",
        "automation/app.py": "import protocol\n",
        "protocol.py": "value = 1\n",
        "retired.py": "value = 1\n",
        "docs/note.md": "before\n",
        "pyproject.toml": "before\n",
    }
    cases = (
        ({"assistant/app.py": "import protocol\nimport retired\nvalue = 2\n"}, (), ComponentRestart(("assistant",))),
        ({"desktop_ui/ui.py": "value = 2\n"}, (), ComponentRestart(("assistant",))),
        ({"desktop_ui/__init__.py": "value = 2\n"}, (), ComponentRestart(("assistant",))),
        ({"protocol.py": "value = 2\n"}, (), ComponentRestart(("layout", "assistant", "automation"))),
        ({"assistant/app.py": "import protocol\n"}, ("retired.py",), ComponentRestart(("assistant",))),
        ({"assistant/app.py": "import protocol\nimport retired\nimport supervisor_support\n"}, (), ComponentRestart(("assistant",))),
        ({"miryoku/__init__.py": "value = 2\n"}, (), ComponentRestart(("layout",))),
        ({"keeper_control.py": "value = 2\n"}, (), FullRestart.ALL),
        (
            {"supervisor_support.py": "value = 2\n"},
            (),
            FullRestart.ALL,
        ),
        ({"pyproject.toml": "after\n"}, (), FullRestart.ALL),
        ({"docs/note.md": "after\n"}, (), ComponentRestart(())),
    )
    for index, (edits, removed, expected) in enumerate(cases):
        before, after = tmp_path / str(index) / "before", tmp_path / str(index) / "after"
        for root, values in ((before, source), (after, edits)):
            for name, value in values.items():
                destination = root / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(value, encoding="utf-8")
        old, overlay = files(before), files(after)
        new = frozendict({name: value for name, value in old.items() if name not in removed} | overlay)
        versions = Version(frozendict(old), before, before, frozenset()), Version(new, before, after, frozenset(overlay))
        assert restart_plan(versions) == expected


def test_only_the_exact_development_editor_server_is_exempt_from_installed_process_ownership() -> None:
    interpreter = PureWindowsPath(r"C:\Users\Jim.Lundin\Projects\workspace\.venv\Scripts\python.exe")
    extensions = PureWindowsPath(r"C:\Users\Jim.Lundin\.vscode\extensions")
    script = extensions / "ms-python.black-formatter-2026.6.0" / "bundled" / "tool" / "lsp_server.py"
    editor = interpreter, extensions
    assert role_for((str(interpreter).lower(), str(script)), windowed=False, editor=editor) is None
    for arguments in (
        (str(interpreter), str(script), "extra"),
        (r"C:\installed\.python\python.exe", str(script)),
        (str(interpreter), str(script.with_name("workspace.pyw"))),
        (str(interpreter), str(extensions / "unrelated-extension" / "bundled" / "tool" / "lsp_server.py")),
        (str(interpreter), r"C:\elsewhere\lsp_server.py"),
    ):
        assert role_for(arguments, windowed=False, editor=editor) == "runtime"


def test_native_development_tools_can_coexist_with_deployment_only_from_the_reviewed_venv() -> None:
    interpreter = PureWindowsPath(r"C:\Users\Jim.Lundin\Projects\workspace\.venv\Scripts\python.exe")
    editor = (interpreter, PureWindowsPath(r"C:\Users\Jim.Lundin\.vscode\extensions"))
    for module in ("scripts.watch", "scripts.check", "scripts.preview"):
        command: tuple[str, ...] = (str(interpreter), "-B", "-m", module, "--once")
        assert role_for(command, windowed=False, editor=editor) is None
        assert role_for(command, windowed=True, editor=editor) == "runtime"
        assert role_for((r"C:\elsewhere\python.exe", *command[1:]), windowed=False, editor=editor) == "runtime"
    assert role_for((str(interpreter), "-m", "unrelated"), windowed=False, editor=editor) == "runtime"


def test_staging_includes_nested_native_helpers_and_the_checked_source(tmp_path: Path) -> None:
    # Adding a native helper must not leave the release unable to create its stage.
    if shutil.which("git") is None:
        raise unittest.SkipTest("Source deployment tooling requires Git")
    source = tmp_path / "checkout"
    source.mkdir()
    initialized(source)
    root = Path(__file__).resolve().parent.parent

    def ignored_cache(_folder: str, names: list[str]) -> tuple[str, ...]:
        return tuple(name for name in names if name == "__pycache__")

    for package in ("scripts", "winapi"):
        shutil.copytree(root / package, source / package, ignore=ignored_cache)
    for name in ("runtime.py", "keeper.py", "keeper_control.py", "components.py", "protocol.py"):
        shutil.copyfile(root / name, source / name)
    # Staging requires the pins but not their contents. The keeper checks a copy
    # without dotfiles, so the checkout's own pins are not always present.
    for name in PINS:
        (source / name).parent.mkdir(parents=True, exist_ok=True)
        (source / name).write_text(f"{name} fixture\n", encoding="utf-8")
    wanted = files(source, skip_roots=(".git",))
    receipt = tmp_path / "checked.json"
    write_receipt(
        receipt,
        CheckReceipt(
            files=frozendict(wanted),
            tests=(),
            profile="explicit iteration scope",
            platform="win32",
            passed=1,
            skipped=0,
            architecture=CheckedArchitecture(sources=1, exceptions=0),
            elapsed_seconds=1.0,
            checked_at_ns=1,
            standards=True,
        ),
    )
    stage = tmp_path / "workspace-source-test"
    command = (
        "from runtime import activate; activate(); from pathlib import Path; import sys; "
        "from scripts.deploy import stage_source; "
        "stage_source(Path(sys.argv[1]), Path(sys.argv[2]))"
    )
    checked = subprocess.run(
        [sys.executable, "-B", "-c", command, str(receipt), str(stage)], cwd=source, capture_output=True, check=False, timeout=30
    )
    assert checked.returncode == 0, (checked.stdout + checked.stderr).decode("utf-8", errors="replace")
    config, payload = deploy.checked_config(stage)
    assert payload == wanted
    assert config["helpers"] == {name: sha(stage / name) for name in HELPERS}
    assert sha(stage / "winapi" / "_core.py") == wanted["winapi/_core.py"]
    # A new process must load the native coordinator from the staged helpers,
    # without checkout imports masking a missing transitive dependency.
    driver = subprocess.run(
        [
            sys.executable,
            "-B",
            "-c",
            "from pathlib import Path; from scripts.deploy import checked_config; from scripts.deploy_windows import run; checked_config(Path.cwd())",
        ],
        cwd=stage,
        capture_output=True,
        check=False,
        timeout=15,
    )
    assert driver.returncode == 0, (driver.stdout + driver.stderr).decode("utf-8", errors="replace")


def test_deployment_refuses_a_passing_receipt_from_a_check_without_the_standards(tmp_path: Path) -> None:
    # Defect: a plain `scripts.check --receipt` run, which skipped the whole-tree
    # lint and type standards, still releases its source.
    receipt, stage = tmp_path / "checked.json", tmp_path / "workspace-source-test"
    options = Options(full=False, native=False, standards=False, tests=(), receipt=receipt, baseline=tmp_path, timings=tmp_path / "timings.json")
    run = CheckRun(frozendict({"source.py": "0" * 64}), Selection((), (), "explicit iteration scope"), Results(1, 0, (), ()), Report((), (), ()), 1.0)
    with contextlib.redirect_stdout(io.StringIO()):
        assert not publish_check(options, run)
    try:
        deploy.stage_source(receipt, stage)
    except ValueError as error:
        assert "--standards" in str(error), error
    else:
        raise AssertionError("A receipt from a check without the standards was deployable.")
    assert not stage.exists()


def test_native_coordinator_owns_stage_folder_and_detects_source_changes(tmp_path: Path) -> None:
    stage = tmp_path / "workspace-source-test"
    stage.mkdir()
    original_cwd = Path.cwd()
    visits: list[Path] = []

    def coordinate() -> None:
        visits.append(Path.cwd())

    deploy.coordinate_native(stage, coordinate, lambda: True)
    assert visits == [stage] and Path.cwd() == original_cwd
    try:
        deploy.coordinate_native(stage, coordinate, lambda: False)
    except RuntimeError as error:
        assert "Source changed during deployment" in str(error)
    else:
        raise AssertionError("Modified source was reported as successfully deployed")
    assert visits == [stage, stage] and Path.cwd() == original_cwd

    def failed() -> None:
        raise OSError("Coordinator failed")

    try:
        deploy.coordinate_native(stage, failed, lambda: True)
    except OSError:
        pass
    else:
        raise AssertionError("The coordinator failure was lost")
    assert Path.cwd() == original_cwd


def test_release_paths_reject_windows_aliases_and_escapes(tmp_path: Path) -> None:
    for path in ("../escape", "/escape", "a/../b", "a\\b", "a//b", "NUL.txt", "a:stream", "a. ", "a."):
        try:
            member(path)
        except ValueError:
            continue
        raise AssertionError(path)
    try:
        names(("One/file", "one/other"))
    except ValueError:
        pass
    else:
        raise AssertionError("Windows directory aliases must fail")
    (tmp_path / "real").mkdir()
    if os.name == "nt":
        subprocess.run(["cmd.exe", "/c", "mklink", "/J", str(tmp_path / "link"), str(tmp_path / "real")], check=True, capture_output=True)
    else:
        (tmp_path / "link").symlink_to(tmp_path / "real", target_is_directory=True)
    try:
        file_at(tmp_path, "link/file")
    except ValueError:
        pass
    else:
        raise AssertionError("Linked destinations must fail")


def test_source_contract_excludes_runtime_and_bytecode() -> None:
    pins = {".python-version": "a" * 64, "requirements/windows-py315.lock": "b" * 64}
    for extra in (".python/private", ".runtime/private", "a/__pycache__/b.pyc", "a.pyc"):
        try:
            source_map({"files": pins | {extra: "c" * 64}})
        except ValueError:
            continue
        raise AssertionError(extra)


def payload_zip(path: Path, records: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in records.items():
            archive.writestr("workspace/" + name, data)
    return path


def header_offset(info: zipfile.ZipInfo) -> int:
    return info.header_offset


def local_record(path: Path, name: str) -> bytes:
    """The complete local record of one member: header, compressed data and descriptor."""
    with zipfile.ZipFile(path) as archive:
        ordered = sorted(archive.infolist(), key=header_offset)
        index = next(position for position, info in enumerate(ordered) if info.filename == name)
        end = ordered[index + 1].header_offset if index + 1 < len(ordered) else archive.start_dir
        return path.read_bytes()[ordered[index].header_offset : end]


def test_source_repack_preserves_compressed_records_without_opening_them(tmp_path: Path) -> None:
    # Detect regenerating runtime or source bytes, or keeping stale source records.
    prior, output = tmp_path / "prior.zip", tmp_path / "fresh.zip"
    payload = payload_zip(tmp_path / "source.zip", {"new.py": b"answer = 42\n"})
    data = os.urandom(2_000_000)
    with zipfile.ZipFile(prior, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("workspace/.runtime/runtime.bin", data)
        archive.writestr("workspace/.python/pythonw.exe", b"retired interpreter")
        archive.writestr("workspace/removed.py", "stale")
    repack(prior, payload, output)
    assert local_record(output, "workspace/.runtime/runtime.bin") == local_record(prior, "workspace/.runtime/runtime.bin")
    assert local_record(output, "workspace/new.py") == local_record(payload, "workspace/new.py")
    with zipfile.ZipFile(output) as archive:
        assert archive.read("workspace/.runtime/runtime.bin") == data
        assert archive.read("workspace/new.py") == b"answer = 42\n"
        assert set(archive.namelist()) == {"workspace/.runtime/runtime.bin", "workspace/new.py"}
    assert prior.stat().st_size - 1000 < output.stat().st_size < prior.stat().st_size + 1000


def test_repack_rejects_duplicate_or_unsafe_archive_members(tmp_path: Path) -> None:
    prior = payload_zip(tmp_path / "prior.zip", {"../escape": b"bad"})
    runtime = payload_zip(tmp_path / "runtime.zip", {".runtime/private": b"bad"})
    empty = payload_zip(tmp_path / "empty.zip", {})
    for previous, payload in ((prior, empty), (empty, runtime)):
        try:
            repack(previous, payload, tmp_path / (previous.stem + payload.stem + ".zip"))
        except ValueError:
            continue
        raise AssertionError("Unsafe ZIP member accepted")


def test_repack_preserves_descriptor_and_zip64_records(tmp_path: Path) -> None:
    class Unseekable(io.BytesIO):
        def seekable(self) -> bool:
            return False

        def seek(self, offset: int, whence: int = os.SEEK_SET) -> int:
            raise OSError("nonseekable writer")

    stream = Unseekable()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive, archive.open("workspace/.runtime/library", "w", force_zip64=True) as writer:
        writer.write(b"important runtime bytes" * 500)
    prior = tmp_path / "prior.zip"
    prior.write_bytes(stream.getvalue())
    output = tmp_path / "next.zip"
    repack(prior, payload_zip(tmp_path / "source.zip", {"next.py": b"next = True\n"}), output)
    with zipfile.ZipFile(output) as archive:
        assert archive.read("workspace/.runtime/library") == b"important runtime bytes" * 500
        assert archive.read("workspace/next.py") == b"next = True\n"


def test_process_classifier_preserves_only_independent_browser_host() -> None:
    assert role_for(("pythonw.exe", "-B", "-m", "assistant.browser_host", "--generation", "1"), windowed=True) is None
    assert role_for(("pythonw.exe", "-m", "assistant"), windowed=True) == "assistant"
    assert role_for(("pythonw.exe", "-m", "miryoku"), windowed=True) == "layout"
    assert role_for(("pythonw.exe", "workspace.pyw"), windowed=True) == "keeper"
    assert role_for(("python.exe", "test.py", "-m", "assistant.browser_host"), windowed=False) == "runtime"
    assert role_for(("pythonw.exe", "test.py", "workspace.pyw"), windowed=True) == "runtime"


def test_process_group_rejects_unowned_or_duplicate_children() -> None:
    rows: tuple[Process, ...] = (
        Process(10, 1, "keeper", "pythonw.exe", 1),
        Process(11, 10, "assistant", "pythonw.exe", 1),
        Process(12, 10, "automation", "pythonw.exe", 1),
        Process(13, 10, "layout", "pythonw.exe", 1),
    )
    assert group(rows)["assistant"].pid == 11
    variants: tuple[tuple[Process, ...], ...] = ((*rows, rows[1]), (*rows, Process(14, 99, "runtime", "python.exe", 1)), rows[:-1])
    for bad in variants:
        try:
            group(bad)
        except RuntimeError:
            continue
        raise AssertionError("Unowned/incomplete process tree accepted")


def test_partial_install_restores_verified_before_images(tmp_path: Path) -> None:
    """Drive the real coordinator prepare/install/copy/restore path with owned temp files."""

    class LocalRelease(Release):
        def __init__(self, root: Path = tmp_path, *, fail_copy: bool = True) -> None:
            self.fail_copy = fail_copy
            self.stage = root / "stage"
            self.live = root / "live"
            self.profile = root / "profile"
            self.state = self.profile / "keeper"
            self.archive = root / "bundle.zip"
            self.stage.mkdir()
            installed = {".runtime/preserved": b"pinned runtime bytes", "old.py": b"old source", "retired.py": b"retired", "kept.py": b"kept"}
            pins = {name: f"{name} pin\n".encode() for name in PINS}
            for name, data in (installed | pins).items():
                (self.live / name).parent.mkdir(parents=True, exist_ok=True)
                (self.live / name).write_bytes(data)
            payload_zip(self.archive, installed | pins)
            self.config, self.wanted = staged(self.stage, pins | {"old.py": b"new source", "added.py": b"new file", "kept.py": b"kept"})
            self._baseline = None
            self.copies = 0
            self.restored = False

        def stop(self) -> None:
            write(
                self.stage / "stopped.json",
                {"stage_id": self.stage.name, "was_running": False, "clean_exit": True, "processes_before": [], "exits": []},
            )

        @contextlib.contextmanager
        def exclusive(self) -> Generator[None]:
            yield

        def copy(self, source: Path, destination: Path) -> None:
            self.copies += 1
            if self.fail_copy and self.copies == 2:
                raise OSError("injected second source replacement failure")
            super().copy(source, destination)

        def inventory(self) -> tuple[Process, ...]:
            return ()

        def reload(self) -> None:
            # Both successful source installation and rollback reach this real
            # coordinator seam before any archive publication is allowed.
            assert (self.live / "old.py").read_bytes() == (b"old source" if self.fail_copy else b"new source")
            assert (self.live / "added.py").exists() is not self.fail_copy
            assert (self.live / "retired.py").exists() is self.fail_copy
            assert sha(self.archive) == self.prepared()["old_archive_sha256"]
            self.receipt("reloaded.json", {"was_running": False, "left_stopped": True})
            self.restored = True

    release = LocalRelease()
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            drive(release, "deploy")
    except OSError as error:
        assert "second source replacement" in str(error)
    else:
        raise AssertionError("A failed install must report failure")
    assert release.restored
    assert (release.stage / "rollback.json").is_file()
    assert not (release.stage / "verified.json").exists()
    baseline = release.prepared()
    assert release.runtime_fingerprint(baseline["runtime"]) == baseline["runtime_fingerprint"]
    success_root = tmp_path / "success"
    success_root.mkdir()
    success = LocalRelease(success_root, fail_copy=False)
    with contextlib.redirect_stdout(io.StringIO()):
        drive(success, "deploy")
    assert success.restored
    baseline = success.prepared()
    assert sha(success.archive) == baseline["new_archive_sha256"]
    assert sha(success.stage / "backup" / "previous-bundle.zip") == baseline["old_archive_sha256"]
    assert (success.stage / "verified.json").is_file()
    assert (success.stage / "archive-published.json").is_file()
    # The next release reuses this audit's source manifest in place of the archive's records.
    audit = RUNTIME_AUDIT.validate_json((success.profile / "deployment" / "runtime-audit.json").read_bytes(), strict=True)
    assert audit["source"] == zip_files(success.archive, source_only=True)


def test_runtime_metadata_detects_changed_members_and_bytes(tmp_path: Path) -> None:
    """The cheap metadata audit still invalidates an ordinary modified runtime."""

    class LocalRelease(Release):
        def __init__(self) -> None:
            self.live = tmp_path

    for folder in (".runtime",):
        (tmp_path / folder).mkdir()
        (tmp_path / folder / "library").write_bytes(b"old")
    release = LocalRelease()
    expected = {".runtime/library": "0" * 64}
    before = release.runtime_fingerprint(expected)
    (tmp_path / ".runtime/library").write_bytes(b"new longer library")
    assert release.runtime_fingerprint(expected) != before
    (tmp_path / ".runtime/added").write_bytes(b"new member")
    assert ".runtime/added" in release.runtime_fingerprint(expected)
    (tmp_path / ".runtime/__pycache__").mkdir()
    (tmp_path / ".runtime/__pycache__/generated.pyc").write_bytes(b"generated")
    assert ".runtime/__pycache__/generated.pyc" not in release.runtime_fingerprint(expected)


def test_a_deployment_refuses_to_erase_an_agent_install_the_checkout_lacks() -> None:
    # Detect a deploy silently reverting a keeper-installed change, or refusing one the checkout already contains.
    deployed = {"a.py": "1", "b.py": "1", "c.py": "1", "d.py": "1"}
    installed = {"a.py": "agent", "b.py": "merged", "d.py": "1"}
    wanted = {"a.py": "1", "b.py": "merged", "c.py": "1", "d.py": "2"}
    assert installed_drift(deployed, installed, wanted) == ("a.py", "c.py")
    assert installed_drift(deployed, deployed, wanted) == ()
    assert installed_drift({}, installed, wanted) == ()
