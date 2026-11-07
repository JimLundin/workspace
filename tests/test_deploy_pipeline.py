"""The deploy's own boundaries: staged bytes, runtime pins and release paths."""

import os
import shutil
import subprocess
import time
import unittest
from pathlib import Path

from keeper_control import InstallRefused, InstallStarted, record_install
from scripts import deploy
from scripts.deploy_files import INTERPRETER, PINS, file_at, member, names, sha, source_map
from tests.git_fixture import initialized


def checkout(folder: Path, files: dict[str, bytes]) -> dict[str, str]:
    initialized(folder)
    for name, data in files.items():
        (folder / name).parent.mkdir(parents=True, exist_ok=True)
        (folder / name).write_bytes(data)
    return {name: sha(folder / name) for name in files}


def test_staging_copies_exactly_the_working_tree_bytes(tmp_path: Path) -> None:
    # Defects: a deploy rewrites line endings or misses a source file the keeper
    # then deletes from the installed copy.
    if shutil.which("git") is None:
        raise unittest.SkipTest("Deploy reads the Git-listed working tree")
    source = tmp_path / "checkout"
    wanted = checkout(source, {**dict.fromkeys(PINS, b"pin\n"), "assistant/app.py": b"value = 1\r\n", "docs/note.md": b"note\n"})
    stage = tmp_path / "stage"
    assert deploy.stage_source(stage, checkout=source) == wanted
    assert {name: sha(stage / name) for name in wanted} == wanted


def test_only_a_changed_python_version_is_refused_before_anything_is_installed(tmp_path: Path) -> None:
    # Defects: a deploy installs code for a Python the installed copy doesn't run,
    # or still refuses a dependency lock change, which the keeper now installs.
    live = tmp_path / "live"
    for name in PINS:
        (live / name).parent.mkdir(parents=True, exist_ok=True)
        (live / name).write_bytes(b"installed\n")
    wanted = {name: sha(live / name) for name in PINS}
    (live / PINS[1]).write_bytes(b"newer lock\n")
    assert not deploy.changed_interpreter(wanted, live)
    (live / INTERPRETER).write_bytes(b"3.16\n")
    assert deploy.changed_interpreter(wanted, live)


def test_a_retried_deploy_waits_for_a_result_newer_than_its_request(tmp_path: Path) -> None:
    # Defect: retrying an identical deploy reads the keeper's earlier result for
    # the same digest, reports it and deletes the stage the keeper still needs.
    digest = "d" * 64
    record_install(tmp_path, InstallRefused(digest, "Update undone: it didn't start."))
    before = deploy.result_stamp(tmp_path)
    with unittest.TestCase().assertRaises(SystemExit):
        deploy.wait_for(tmp_path, digest, before=before, deadline=time.monotonic() + 0.05)
    record_install(tmp_path, InstallStarted(digest, "Deploy", "v" * 40))
    assert deploy.wait_for(tmp_path, digest, before=before, deadline=time.monotonic() + 5) == InstallStarted(digest, "Deploy", "v" * 40)


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
