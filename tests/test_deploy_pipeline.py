"""The deploy's own boundaries: check receipts, staged bytes and runtime pins."""

import contextlib
import io
import os
import shutil
import subprocess
import unittest
from pathlib import Path

from scripts import deploy
from scripts.architecture import Report
from scripts.check import CheckRun, Options, publish_check
from scripts.check_results import Results, Selection
from scripts.deploy_files import PINS, CheckedArchitecture, CheckReceipt, file_at, member, names, sha, source_map, write_receipt
from tests.git_fixture import initialized


def receipt_for(path: Path, files: dict[str, str]) -> Path:
    write_receipt(
        path,
        CheckReceipt(
            files=frozendict(files),
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
    return path


def checkout(folder: Path, files: dict[str, bytes]) -> dict[str, str]:
    initialized(folder)
    for name, data in files.items():
        (folder / name).parent.mkdir(parents=True, exist_ok=True)
        (folder / name).write_bytes(data)
    return {name: sha(folder / name) for name in files}


def test_staging_copies_exactly_the_checked_bytes_and_refuses_a_changed_tree(tmp_path: Path) -> None:
    # Defects: a deploy installs bytes the receipt never checked, or misses a
    # checked file the keeper then deletes from the installed copy.
    if shutil.which("git") is None:
        raise unittest.SkipTest("Deploy reads the Git-listed working tree")
    source = tmp_path / "checkout"
    wanted = checkout(source, {**dict.fromkeys(PINS, b"pin\n"), "assistant/app.py": b"value = 1\r\n", "docs/note.md": b"note\n"})
    receipt = receipt_for(tmp_path / "checked.json", wanted)
    stage = tmp_path / "stage"
    assert deploy.stage_source(receipt, stage, checkout=source) == wanted
    assert {name: sha(stage / name) for name in wanted} == wanted
    (source / "assistant/app.py").write_bytes(b"value = 2\n")
    with unittest.TestCase().assertRaisesRegex(RuntimeError, "differs from the checked source"):
        deploy.stage_source(receipt, tmp_path / "second", checkout=source)
    assert not (tmp_path / "second").exists()


def test_a_changed_runtime_pin_is_named_before_anything_is_installed(tmp_path: Path) -> None:
    # Defect: a deploy installs code that needs dependencies the installed bundle lacks.
    live = tmp_path / "live"
    for name in PINS:
        (live / name).parent.mkdir(parents=True, exist_ok=True)
        (live / name).write_bytes(b"installed\n")
    wanted = {name: sha(live / name) for name in PINS}
    assert deploy.changed_pins(wanted, live) == ()
    (live / PINS[1]).write_bytes(b"newer\n")
    assert deploy.changed_pins(wanted, live) == (PINS[1],)


def test_deployment_refuses_a_passing_receipt_from_a_check_without_the_standards(tmp_path: Path) -> None:
    # Defect: a plain `scripts.check --receipt` run, which skipped the whole-tree
    # lint and type standards, still releases its source.
    receipt, stage = tmp_path / "checked.json", tmp_path / "stage"
    options = Options(full=False, native=False, standards=False, tests=(), receipt=receipt, baseline=tmp_path, timings=tmp_path / "timings.json")
    run = CheckRun(frozendict({"source.py": "0" * 64}), Selection((), (), "explicit iteration scope"), Results(1, 0, (), ()), Report((), (), ()), 1.0)
    with contextlib.redirect_stdout(io.StringIO()):
        assert not publish_check(options, run)
    try:
        deploy.stage_source(receipt, stage, checkout=tmp_path)
    except ValueError as error:
        assert "--standards" in str(error), error
    else:
        raise AssertionError("A receipt from a check without the standards was deployable.")
    assert not stage.exists()


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
