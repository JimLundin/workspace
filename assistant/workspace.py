"""The agent's workspace: a copy of Workspace's source it may edit freely. Nothing
it does here touches the running workspace; the keeper installs the workspace, after
checking it, when asked (see keeper.py)."""

import difflib
import os
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from assistant import commands
from keeper import CHECK_S, LIVE, PROTECTED, WORKSPACE, console_python, copy_source, source_digest, source_files
from selfcheck import compile_all


class SourceError(Exception):
    """A change the workspace refuses; its message is for the agent."""


@dataclass(frozen=True, slots=True)
class CheckCompleted:
    passed: bool = field(kw_only=True)
    report: str


@dataclass(frozen=True, slots=True)
class CheckInterrupted:
    reason: str


type CheckResult = CheckCompleted | CheckInterrupted


def development_python() -> Path | None:
    """The development environment's interpreter, which has the Ruff, pyright and
    mypy CI uses; the bundled runtime cannot carry Ruff's executable."""
    configured = os.environ.get("WORKSPACE_STANDARDS_PYTHON")
    python = Path(configured) if configured else Path.home() / "Projects" / "workspace" / ".venv" / "Scripts" / "python.exe"
    return python if python.is_file() else None


class Workspace:
    __slots__ = ("live", "prepared", "root", "standards")

    # Four parameters: the draft, the running version it is checked against, and
    # the standards interpreter are one installation's fixed facts; resume selects
    # whether an existing draft is kept.
    def __init__(self, live: Path = LIVE, root: Path = WORKSPACE, *, resume: bool = False, standards: Path | None = None) -> None:
        self.live = live
        self.root = root
        self.standards = standards
        self.prepared = resume and (root / ".workspace-workspace-ready").is_file()

    def ensure(self) -> None:
        """Copy source on the first source tool, then keep edits for follow-up requests."""
        if not self.prepared:
            self.reset()

    def reset(self) -> None:
        """Starts over from the running version."""
        self.prepared = False
        (self.root / ".workspace-workspace-ready").unlink(missing_ok=True)
        copy_source(self.live, self.root)
        (self.root / ".workspace-workspace-ready").write_text("ready", encoding="utf-8")
        self.prepared = True

    def files(self) -> list[str]:
        return source_files(self.root)

    def _path(self, name: str) -> Path:
        relative = PurePosixPath(name.replace("\\", "/"))
        if relative.is_absolute() or ".." in relative.parts or ":" in name or any(p.endswith((".", " ")) for p in relative.parts):
            raise SourceError(f"{name} is outside Workspace's source")
        path = self.root / relative
        if not path.resolve().is_relative_to(self.root.resolve()):
            raise SourceError(f"{name} is outside Workspace's source")
        return path

    def _writable(self, name: str) -> Path:
        path = self._path(name)
        if PurePosixPath(name.replace("\\", "/")).as_posix().lower() in PROTECTED or any(
            part.lower() in (".runtime", ".python") for part in PurePosixPath(name.replace("\\", "/")).parts
        ):
            raise SourceError(f"{name} is protected: the keeper and its checks can only be changed by a person")
        return path

    def read(self, name: str) -> str:
        path = self._path(name)
        if not path.is_file():
            raise SourceError(f"there's no file {name}")
        return path.read_text(encoding="utf-8")

    def write(self, name: str, text: str) -> None:
        path = self._writable(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Source is LF everywhere. Windows text mode wrote CRLF, so every agent edit
        # rewrote whole files' line endings in diffs and commits.
        path.write_text(text, encoding="utf-8", newline="\n")

    def replace(self, name: str, old: str, new: str) -> None:
        """Replaces text that appears exactly once."""
        text = self.read(name)
        count = text.count(old)
        if count != 1:
            raise SourceError(f"the text to replace was not found in {name}" if count == 0 else f"the text to replace is in {name} {count} times")
        self.write(name, text.replace(old, new))

    def delete(self, name: str) -> None:
        path = self._writable(name)
        if not path.is_file():
            raise SourceError(f"there's no file {name}")
        path.unlink()

    def changes(self) -> list[str]:
        """What differs from the running version: `added x`, `changed y`, `deleted z`."""
        mine, running = set(self.files()), set(source_files(self.live))
        changed = [f for f in sorted(mine & running) if (self.root / f).read_bytes() != (self.live / f).read_bytes()]
        return [
            *(f"added {f}" for f in sorted(mine - running)),
            *(f"changed {f}" for f in changed),
            *(f"deleted {f}" for f in sorted(running - mine)),
        ]

    def diff(self) -> str:
        """A unified diff against the running version."""
        parts: list[str] = []
        for change in self.changes():
            name = change.split(" ", 1)[1]
            before = (self.live / name).read_text(encoding="utf-8", errors="replace").splitlines(keepends=True) if (self.live / name).exists() else []
            after = (self.root / name).read_text(encoding="utf-8", errors="replace").splitlines(keepends=True) if (self.root / name).exists() else []
            parts.append("".join(difflib.unified_diff(before, after, f"running/{name}", f"changed/{name}")))
        return "\n".join(parts)

    def protected_problem(self) -> str:
        """Detect stale or altered protected source before executing or submitting a draft."""
        for name in sorted(PROTECTED):
            draft, live = self.root / name, self.live / name
            if draft.is_file() != live.is_file() or (draft.is_file() and draft.read_bytes() != live.read_bytes()):
                return (
                    f"The protected file {name} differs from the running version. "
                    "Preserve your intended edits, refresh the source copy from the running version, "
                    "and reapply only those edits before checking again."
                )
        return ""

    def validate(self) -> tuple[bool, str]:
        """Reject an un-installable baseline before spending time on syntax or runtime checks."""
        if problem := self.protected_problem():
            return False, problem
        problems: list[str] = []
        compile_all(self.root, problems)
        return not problems, "\n".join(problems) or "Syntax checks pass."

    def check(self, timeout_s: float = CHECK_S) -> tuple[bool, str]:
        result = self.inspect_check(timeout_s)
        return (result.passed, result.report) if isinstance(result, CheckCompleted) else (False, result.reason)

    def inspect_check(
        self,
        timeout_s: float = CHECK_S,
        *,
        affected: bool = False,
        cancel: threading.Event | None = None,
    ) -> CheckResult:
        """Run the stable selfcheck on a fresh copy so tests cannot leave stale bytecode in the draft."""
        if problem := self.protected_problem():
            return CheckCompleted(passed=False, report=problem)
        with tempfile.TemporaryDirectory(prefix="workspace-check-") as scratch:
            candidate = Path(scratch) / "source"
            copy_source(self.root, candidate)
            digest = source_digest(candidate)
            command = [console_python(), str(self.live / "selfcheck.py"), str(candidate)]
            if affected:
                # Native modules included: an install refusal costs the agent a
                # keeper round trip, so it sees every failure the keeper would.
                command.extend(("--changed-from", str(self.live)))
            code, report = commands.run(command, timeout_s=timeout_s, cancel=cancel)
            if code == -1:
                return CheckInterrupted(report)
            if source_digest(candidate) != digest:
                return CheckCompleted(passed=False, report="Runtime checks changed the candidate source; fix the tests and check again.")
            if code != 0 or not affected:
                return CheckCompleted(passed=code == 0, report=report)
            if self.standards is None:
                return CheckCompleted(
                    passed=True, report=report + "\nStandards not run: no development environment; CI applies them after the push.\n"
                )
            # After the digest comparison: the tools leave caches in the scratch copy.
            standards = [str(self.standards), "-m", "scripts.check_candidate", str(candidate), "--changed-from", str(self.live)]
            code, findings = commands.run(standards, cwd=str(self.live), timeout_s=timeout_s, cancel=cancel)
            if code == -1:
                return CheckInterrupted(findings)
            return CheckCompleted(passed=code == 0, report=report + "\n" + findings)
