"""Publish through real local Git repositories; never contact GitHub in tests."""

import os
import shutil
import sqlite3
import subprocess
import sys
import threading
from collections.abc import Callable
from contextlib import closing
from pathlib import Path
from unittest import TestCase

from assistant.publishing import Installed, Landing, PublishError, git, land_installed, publish_source
from automation.actions import Change, Operation, Resources
from automation.execution import WorkExecution
from contracts.task import ActionVerified, NoVerification
from keeper import copy_source
from tests.git_fixture import initialized
from tests.test_work_actions import claimed
from tests.test_workspace import live_tree

ROOT = Path(__file__).resolve().parent.parent


def repository(tmp_path: Path) -> tuple[Path, Path, Path]:
    live = live_tree(tmp_path / "live")
    git(live, "init")
    git(live, "symbolic-ref", "HEAD", "refs/heads/main")
    git(live, "add", ".")
    git(live, "-c", "user.name=Workspace Test", "-c", "user.email=workspace@example.invalid", "commit", "-m", "baseline")
    remote = tmp_path / "remote.git"
    git(tmp_path, "clone", "--bare", str(live), str(remote))
    workspace = tmp_path / "workspace"
    copy_source(live, workspace)
    (workspace / "config.py").write_text("GREETING = 'hello'\n", encoding="utf-8")
    return live, workspace, remote


def test_an_installed_change_lands_on_main_once_and_never_over_newer_work(tmp_path: Path) -> None:
    # Detect a verified install never reaching main, landing twice, or overwriting a change pushed meanwhile.
    live, workspace, remote = repository(tmp_path)
    landing = Landing(str(remote), "main")
    base = tmp_path / "base"
    copy_source(live, base)
    installed = Installed(workspace, base, "English greeting")
    result = land_installed(installed, landing)
    head = git(remote, "rev-parse", "refs/heads/main")
    assert result == f"Merged into main and pushed as {head}."
    assert git(remote, "show", "main:config.py") == "GREETING = 'hello'"
    assert git(remote, "log", "-1", "--format=%s", "main") == "English greeting"
    assert land_installed(installed, landing) == f"main already contains the installed change ({head})."
    (workspace / "config.py").write_text("GREETING = 'hi'\n", encoding="utf-8")
    try:
        land_installed(installed, landing)
    except PublishError as error:
        assert "changed since this update was built" in str(error)
    else:
        raise AssertionError("a moved branch must not be overwritten")
    assert git(remote, "rev-parse", "refs/heads/main") == head


def test_failed_checks_and_diverged_base_refuse_publication(tmp_path: Path) -> None:
    # The refusal paths leave the repository unchanged. Reset only the
    # candidate inputs between them; actual Git and candidate checks still run.
    live, workspace, remote = repository(tmp_path)
    (workspace / "config.py").write_text("GREETING = ''\n", encoding="utf-8")
    try:
        publish_source(live, workspace, "broken", lambda: False, remote=str(remote))
    except PublishError as error:
        assert "Runtime checks failed" in str(error)
    else:
        raise AssertionError("failing tests must prevent push")
    assert not git(remote, "for-each-ref", "refs/heads/workspace/")

    (workspace / "config.py").write_text("GREETING = 'hello'\n", encoding="utf-8")
    (live / "config.py").write_text("GREETING = 'local change'\n", encoding="utf-8")
    try:
        publish_source(live, workspace, "change", lambda: False, remote=str(remote))
    except PublishError as error:
        assert "remote base differs" in str(error)
    else:
        raise AssertionError("diverged base must be refused")


def test_durable_publication_records_before_candidate_code_and_remote_push(tmp_path: Path) -> None:
    store, claim, clock = claimed(tmp_path)
    live, workspace, remote = repository(tmp_path / "repo")
    main = git(remote, "rev-parse", "refs/heads/main")
    work = WorkExecution(claim, store, Resources(), clock=clock)
    marker = tmp_path / "candidate-executed"
    (workspace / "probe.py").write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).touch()\n",
        encoding="utf-8",
    )

    operation = Operation.of("publish_changes", {"summary": "Checked update"})

    def execute(perform: Callable[[], str]) -> str:
        return work.actions.execute(
            Change(("exclusive",)).specification(operation, NoVerification.NONE),
            perform,
            bool,
            threading.Event(),
            verify=lambda _: ActionVerified("Remote readback matched the published commit."),
        )

    with closing(sqlite3.connect(tmp_path / "work.sqlite3")) as database, database:
        database.execute("CREATE TRIGGER refuse_publication BEFORE INSERT ON actions BEGIN SELECT RAISE(ABORT,'cannot record'); END")
    with TestCase().assertRaises(sqlite3.DatabaseError):
        publish_source(live, workspace, "Checked update", lambda: False, remote=str(remote), branch="workspace/agent-durable", execute=execute)
    assert not marker.exists() and not git(remote, "for-each-ref", "refs/heads/workspace/")
    with closing(sqlite3.connect(tmp_path / "work.sqlite3")) as database, database:
        database.execute("DROP TRIGGER refuse_publication")
    result = publish_source(live, workspace, "Checked update", lambda: False, remote=str(remote), branch="workspace/agent-durable", execute=execute)
    assert marker.exists() and "Published" in result
    assert git(remote, "show", "refs/heads/workspace/agent-durable:config.py") == "GREETING = 'hello'"
    # Publication pushes a review branch only: main and the running source stay put.
    assert git(remote, "rev-parse", "refs/heads/main") == main
    assert "'hej'" in (live / "config.py").read_text(encoding="utf-8")
    assert isinstance(store.actions("task")[0].outcome, ActionVerified)


def test_git_commits_land_in_the_named_folder_whatever_repository_the_parent_locates(tmp_path: Path) -> None:
    # Defect: an inherited GIT_DIR, GIT_WORK_TREE or GIT_INDEX_FILE overrides
    # `git -C folder`, so a temporary repository's init and commit rewrite the
    # repository the parent environment points at, including its configuration.
    decoy, folder = tmp_path / "decoy", tmp_path / "folder"
    initialized(decoy)
    folder.mkdir()
    (folder / "value.txt").write_text("temporary\n", encoding="utf-8")
    script = (
        "import sys; from pathlib import Path; from assistant.publishing import git; folder = Path(sys.argv[1]); "
        "git(folder, 'init'); git(folder, 'add', '.'); "
        "git(folder, '-c', 'user.name=Workspace Test', '-c', 'user.email=workspace@example.invalid', 'commit', '-m', 'temporary')"
    )
    located = {"GIT_DIR": str(decoy / ".git"), "GIT_WORK_TREE": str(decoy), "GIT_INDEX_FILE": str(decoy / ".git" / "index")}
    result = subprocess.run(
        (sys.executable, "-c", script, str(folder)),
        cwd=ROOT,
        env={**os.environ, **located},
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert git(folder, "log", "--format=%s") == "temporary"
    assert git(decoy, "for-each-ref") == "" and not (decoy / ".git" / "index").exists()
    assert "worktree" not in (decoy / ".git" / "config").read_text(encoding="utf-8")


if shutil.which("git") is None:
    import unittest

    raise unittest.SkipTest("Git publishing tests need Git")
