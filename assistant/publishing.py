"""Publish checked source to a new Git branch, independently of local installation."""

import os
import subprocess
import tempfile
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from assistant.git_environment import isolated
from keeper import CHECK_S, CREATE_NO_WINDOW, console_python, copy_source, source_diff, source_digest, source_files

DEFAULT_REMOTE = "https://github.com/JimLundin/workspace.git"


class PublishError(Exception):
    """A publishing failure whose message can be shown to the user."""


def git(folder: Path, *arguments: str) -> str:
    # The repository comes only from `folder`, never from an inherited location.
    env = isolated({**os.environ, "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "Never"})
    try:
        result = subprocess.run(
            ["git", "-C", str(folder), *arguments],
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
            check=False,
            creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except FileNotFoundError as error:
        raise PublishError("Publishing needs Git for Windows on PATH and GitHub authentication.") from error
    except subprocess.TimeoutExpired as error:
        raise PublishError("Git timed out; check network access and GitHub authentication.") from error
    if result.returncode:
        raise PublishError(f"Git {arguments[0]} failed: {(result.stderr or result.stdout)[-2000:]}")
    return result.stdout.strip()


def same_source(first: Path, second: Path) -> bool:
    """The same source files with the same contents, ignoring CRLF/LF differences."""
    names = source_files(first)
    return names == source_files(second) and all(
        (first / name).read_bytes().replace(b"\r\n", b"\n") == (second / name).read_bytes().replace(b"\r\n", b"\n") for name in names
    )


def commit_all(checkout: Path, names: list[str], summary: str) -> str:
    """Commit `names` as the agent; the new commit's id."""
    git(checkout, "add", "-A", "--", *names)
    git(
        checkout,
        "-c",
        f"user.name={os.environ.get('WORKSPACE_GIT_AUTHOR_NAME', 'Workspace Agent')}",
        "-c",
        f"user.email={os.environ.get('WORKSPACE_GIT_AUTHOR_EMAIL', 'workspace@localhost')}",
        "commit",
        "-m",
        summary,
    )
    return git(checkout, "rev-parse", "HEAD")


@dataclass(frozen=True, slots=True)
class Landing:
    """Where installed self-changes land: the remote and its branch."""

    remote: str
    branch: str


@dataclass(frozen=True, slots=True)
class Installed:
    """A keeper-installed change: the running source, the snapshot it replaced and its summary."""

    source: Path
    base: Path
    summary: str


def land_installed(change: Installed, landing: Landing) -> str:
    """Commit the keeper-installed source onto the branch it was built from and push it.

    The keeper just checked and installed these exact bytes, so this runs no checks.
    `base` is the keeper's snapshot of what ran before the install: the branch must
    still match it, or another change landed meanwhile and this refuses rather than
    overwrite it. Landing again after a success finds the branch already up to date.
    """
    installed, base, summary = change.source, change.base, change.summary
    if not summary.strip():
        raise PublishError("A commit summary is required.")
    with tempfile.TemporaryDirectory(prefix="workspace-land-") as scratch:
        checkout = Path(scratch) / "checkout"
        git(
            Path(scratch),
            "-c",
            "core.autocrlf=false",
            "clone",
            "--quiet",
            "--single-branch",
            "--branch",
            landing.branch,
            "--",
            landing.remote,
            str(checkout),
        )
        if same_source(checkout, installed):
            return f"{landing.branch} already contains the installed change ({git(checkout, 'rev-parse', 'HEAD')})."
        if not same_source(checkout, base):
            raise PublishError(
                f"{landing.branch} changed since this update was built; it was installed but not merged. "
                "Bring the installed change into the repository by hand."
            )
        names = sorted(set(source_files(checkout)) | set(source_files(installed)))
        copy_source(installed, checkout)
        commit = commit_all(checkout, names, summary)
        git(checkout, "push", "origin", f"HEAD:refs/heads/{landing.branch}")
        actual = git(checkout, "ls-remote", "--exit-code", "origin", f"refs/heads/{landing.branch}")
        if actual.split() != [commit, f"refs/heads/{landing.branch}"]:
            raise PublishError("The push returned but remote readback did not match. Inspect the branch before retrying.")
        return f"Merged into {landing.branch} and pushed as {commit}."


def publish_source(  # noqa: PLR0913 - git publication options and test seams
    live: Path,
    workspace: Path,
    summary: str,
    stopped: Callable[[], bool],
    *,
    remote: str = DEFAULT_REMOTE,
    base: str = "main",
    branch: str | None = None,
    execute: Callable[[Callable[[], str]], str] | None = None,
) -> str:
    """Freeze, test, commit and push. No force push and no edits to live source."""
    if not summary.strip():
        raise PublishError("A commit summary is required.")
    with tempfile.TemporaryDirectory(prefix="workspace-publish-") as scratch:
        root = Path(scratch)
        candidate, checkout = root / "candidate", root / "checkout"
        copy_source(workspace, candidate)
        digest = source_digest(candidate)
        diff = source_diff(live, candidate)
        if not diff:
            raise PublishError("There are no source changes to publish.")
        destination = branch or f"workspace/agent-{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:8]}"
        if stopped():
            raise PublishError("Publishing stopped; nothing was pushed.")

        def publish() -> str:
            git(root, "-c", "core.autocrlf=false", "clone", "--quiet", "--single-branch", "--branch", base, "--", remote, str(checkout))
            if not same_source(checkout, live):
                raise PublishError("The remote base differs from the running source. Update your local workspace before publishing.")
            if source_digest(candidate) != digest:
                raise PublishError("Source changed while publishing; publish it again.")
            try:
                checked = subprocess.run(
                    [console_python(), str(live / "selfcheck.py"), str(candidate)],
                    capture_output=True,
                    timeout=CHECK_S,
                    check=False,
                    creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
            except subprocess.TimeoutExpired as error:
                raise PublishError("Runtime checks timed out; nothing was pushed.") from error
            if checked.returncode:
                report = (checked.stdout + checked.stderr).decode(errors="replace")[-3000:]
                raise PublishError("Runtime checks failed; nothing was pushed.\n" + report)
            if source_digest(candidate) != digest:
                raise PublishError("Runtime checks changed the source; publish it again.")
            names = sorted(set(source_files(checkout)) | set(source_files(candidate)))
            git(checkout, "checkout", "-b", destination)
            copy_source(candidate, checkout)
            commit = commit_all(checkout, names, summary)
            if stopped():
                raise PublishError("Publishing stopped; nothing was pushed.")
            git(checkout, "push", "origin", f"HEAD:refs/heads/{destination}")
            actual = git(checkout, "ls-remote", "--exit-code", "origin", f"refs/heads/{destination}")
            if actual.split() != [commit, f"refs/heads/{destination}"]:
                raise PublishError("The push returned but remote readback did not match. Inspect the branch before retrying.")
            return f"Published {commit} to {remote}, branch {destination}. Main and the running workspace were not changed."

        return publish() if execute is None else execute(publish)
