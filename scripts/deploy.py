"""Install the checkout's source into the installed copy of Workspace through its keeper.

python -m scripts.deploy

The Git-listed source files are staged in Temp and the running keeper checks
and installs them as it installs the agent's changes, restarting only the
programs they affect. With no keeper running, the same version store takes the
files and the copy stays stopped. Rebuild the bundle with scripts/bundle.py
instead when a runtime pin changes.
"""

import argparse
import hashlib
import shutil
import subprocess
import sys
import time
from collections.abc import Mapping
from pathlib import Path

import keeper
from keeper_control import INSTALL_RESULT_FILE, Install, InstallChecking, InstallRefused, InstallStarted, ask, install_result
from scripts.check import source_files
from scripts.deploy_files import PINS, checked_sources, sha
from scripts.development_paths import LIVE, TEMP

WORKSPACE = Path(__file__).resolve().parent.parent
WAIT_S = keeper.CHECK_S + keeper.START_S + 120


def stage_source(stage: Path, *, checkout: Path = WORKSPACE) -> dict[str, str]:
    """Copy the checkout's Git-listed source files into a fresh `stage`, exactly as hashed."""
    wanted = checked_sources(source_files(checkout))
    stage.mkdir(parents=True, exist_ok=False)
    for name in wanted:
        destination = stage / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(checkout / name, destination)
    if {name: sha(stage / name) for name in wanted} != wanted:
        raise RuntimeError("Source changed while it was staged; deploy again.")
    return wanted


def changed_pins(wanted: Mapping[str, str], live: Path) -> tuple[str, ...]:
    """Runtime pins the installed bundle doesn't match: its dependencies would be wrong."""
    return tuple(name for name in PINS if not (live / name).is_file() or hashlib.sha256((live / name).read_bytes()).hexdigest() != wanted[name])


def summary(checkout: Path) -> str:
    head = subprocess.run(["git", "log", "-1", "--format=%h %s"], cwd=checkout, capture_output=True, text=True, check=False).stdout.strip()
    return f"Deploy {head}" if head else "Deploy"


def result_stamp(state: Path) -> int | None:
    """When the keeper last replaced its install result, or None while there is none."""
    try:
        return (state / INSTALL_RESULT_FILE).stat().st_mtime_ns
    except OSError:
        return None


def wait_for(state: Path, digest: str, *, before: int | None, deadline: float) -> InstallStarted | InstallRefused:
    """The keeper's answer to this request; a result recorded `before` it answered an earlier one."""
    reported = False
    while time.monotonic() < deadline:
        if result_stamp(state) == before:
            time.sleep(1)
            continue
        match install_result(state):
            case InstallStarted(digest=installed) as result if installed == digest:
                return result
            case InstallRefused(digest=refused) as result if refused == digest:
                return result
            case InstallChecking(digest=checking) if checking == digest and not reported:
                print("The keeper is checking the change.", flush=True)
                reported = True
            case _:
                pass
        time.sleep(1)
    raise SystemExit(f"The keeper reported no result within {WAIT_S / 60:.0f} minutes; see keeper.log.")


def deploy(live: Path) -> None:
    stage = TEMP / f"workspace-source-{time.time_ns()}"
    try:
        wanted = stage_source(stage)
        if changed := changed_pins(wanted, live):
            raise SystemExit("A runtime pin changed (" + ", ".join(changed) + "); rebuild the bundle with scripts/bundle.py.")
        digest, title = keeper.source_digest(stage), summary(WORKSPACE)
        with keeper.exclusive(keeper.STATE) as stopped:
            if stopped:
                previous = keeper.install_stopped(stage, live, title, state=keeper.STATE, versions=keeper.VERSIONS)
                print(f"Workspace isn't running: installed the files over version {previous[:12]}; it stays stopped.", flush=True)
                return
        # A retried deploy has the same digest as its last result; only a newer result answers it.
        before = result_stamp(keeper.STATE)
        # No fast check stands for these bytes, so the keeper runs the affected portable tests too.
        ask(keeper.REQUESTS, Install(title, digest, None, str(stage)))
        print("Asked the running keeper to install the change.", flush=True)
        match wait_for(keeper.STATE, digest, before=before, deadline=time.monotonic() + WAIT_S):
            case InstallStarted(version=version):
                print(f"Installed; the affected programs are running. Undo restores version {version[:12]}.", flush=True)
            case InstallRefused(reason=reason):
                raise SystemExit(reason)
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    if sys.platform != "win32":
        parser.error("Deploy from Windows with Dev.cmd deploy.")
    deploy(LIVE)


if __name__ == "__main__":
    main()
