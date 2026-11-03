"""Lint, format, type and policy standards for the agent's candidate source.

    python -m scripts.check_candidate CANDIDATE --changed-from BASE

check_changes runs this from the running version with its bundled interpreter after
the protected selfcheck passes, so a self-change fails here instead of reaching main
with errors CI's standards job rejects. Ruff and the architecture and quality
reviews cover the whole candidate; pyright and mypy cover only the Python files
changed from BASE, as `Dev.cmd check` does while editing. Prints only failures
and a one-line summary; exits 1 if any standard failed.
"""

import argparse
import hashlib
import inspect
import shutil
import sys
from pathlib import Path

import runtime

# The tools and Pydantic come from the bundled runtime, activated in main.
lazy from keeper import source_files
lazy from scripts import architecture, check_standards, quality


def changed(candidate: Path, base: Path) -> tuple[str, ...]:
    def digest(path: Path) -> bytes | None:
        return hashlib.sha256(path.read_bytes()).digest() if path.is_file() else None

    return tuple(name for name in source_files(candidate) if digest(candidate / name) != digest(base / name))


# A vendored dot-folder the keeper's source copy omits; both type checkers need it.
TYPESHED = Path("typings") / ".workspace-typeshed"


def failures(candidate: Path, base: Path) -> tuple[str, ...]:
    if not (candidate / TYPESHED).is_dir() and (base / TYPESHED).is_dir():
        shutil.copytree(base / TYPESHED, candidate / TYPESHED)
    lint = tuple(failure.report for failure in check_standards.run((check_standards.LINT, check_standards.FORMAT), candidate))
    try:
        reviewed = architecture.review(candidate)
        policy = tuple(finding.describe() for finding in reviewed.failures)
    except (ValueError, OSError, SyntaxError) as error:
        policy = (f"Architecture review failed: {error}",)
    report = quality.compare(quality.scan(candidate), quality.load(candidate / "docs" / "quality-migrations.json"))
    interfaces = (
        *(finding.describe() for finding in report.failures),
        *(f"Stale quality migration; remove its exact baseline entry: {entry}" for entry in report.stale),
    )
    types = tuple(failure.report for failure in check_standards.run(check_standards.changed_types(changed(candidate, base)), candidate))
    return (*lint, *policy, *interfaces, *types)


def main() -> None:
    runtime.activate(root=Path(__file__).resolve().parent.parent)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--changed-from", type=Path, required=True, metavar="BASE")
    match dict(inspect.getmembers(parser.parse_args())):
        case {"candidate": Path() as candidate, "changed_from": Path() as base}:
            found = failures(candidate.resolve(), base.resolve())
        case _:
            parser.error("Invalid candidate arguments.")
    for failure in found:
        print(failure, flush=True)
    print(f"Standards: {len(found)} failed (Ruff lint and format, architecture, interfaces, pyright and mypy on changed files)", flush=True)
    sys.exit(1 if found else 0)


if __name__ == "__main__":
    main()
