"""Install checked source into the Downloads copy of Workspace through its keeper.

python -m scripts.deploy --check-receipt %TEMP%\\workspace-check.json

The receipt must match every Git-listed source byte. The checked files are
staged in Temp and the running keeper installs them as it installs the agent's
changes, restarting only the programs they affect. With no keeper running, the
same version store takes the files and the copy stays stopped. Rebuild the
bundle with scripts/bundle.py instead when a runtime pin changes.
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
from keeper_control import Install, InstallChecking, InstallRefused, InstallStarted, ask, install_result
from scripts.check import source_files
from scripts.deploy_files import PINS, CheckReceipt, checked_sources, read_receipt, sha
from scripts.development_paths import LIVE, TEMP

WORKSPACE = Path(__file__).resolve().parent.parent
WAIT_S = keeper.CHECK_S + keeper.START_S + 120


def deployable(receipt: Path) -> CheckReceipt:
    """A check receipt that may release source: the run also applied the whole-tree standards."""
    checked = read_receipt(receipt)
    if not checked.standards:
        raise ValueError("The check receipt was written without --standards; rerun Dev.cmd check.")
    return checked


def stage_source(receipt: Path, stage: Path, *, checkout: Path = WORKSPACE) -> dict[str, str]:
    """Copy exactly the checked files into a fresh `stage`; the working tree must still match them."""
    wanted = checked_sources(deployable(receipt).files)
    if source_files(checkout) != wanted:
        raise RuntimeError("The working tree differs from the checked source; rerun checks.")
    stage.mkdir(parents=True, exist_ok=False)
    for name in wanted:
        destination = stage / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(checkout / name, destination)
    if {name: sha(stage / name) for name in wanted} != wanted:
        raise RuntimeError("Source changed while it was staged; rerun checks.")
    return wanted


def changed_pins(wanted: Mapping[str, str], live: Path) -> tuple[str, ...]:
    """Runtime pins the installed bundle doesn't match: its dependencies would be wrong."""
    return tuple(name for name in PINS if not (live / name).is_file() or hashlib.sha256((live / name).read_bytes()).hexdigest() != wanted[name])


def summary(checkout: Path) -> str:
    head = subprocess.run(["git", "log", "-1", "--format=%h %s"], cwd=checkout, capture_output=True, text=True, check=False).stdout.strip()
    return f"Deploy {head}" if head else "Deploy"


def wait_for(digest: str, *, deadline: float) -> InstallStarted | InstallRefused:
    reported = False
    while time.monotonic() < deadline:
        match install_result(keeper.STATE):
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


def deploy(receipt: Path, live: Path) -> None:
    stage = TEMP / f"workspace-source-{time.time_ns()}"
    try:
        wanted = stage_source(receipt, stage)
        if changed := changed_pins(wanted, live):
            raise SystemExit("A runtime pin changed (" + ", ".join(changed) + "); rebuild the bundle with scripts/bundle.py.")
        digest, title = keeper.source_digest(stage), summary(WORKSPACE)
        with keeper.exclusive(keeper.STATE) as stopped:
            if stopped:
                previous = keeper.install_stopped(stage, live, title, state=keeper.STATE, versions=keeper.VERSIONS)
                print(f"Workspace isn't running: installed the files over version {previous[:12]}; it stays stopped.", flush=True)
                return
        ask(keeper.REQUESTS, Install(title, digest, digest, str(stage)))
        print("Asked the running keeper to install the change.", flush=True)
        match wait_for(digest, deadline=time.monotonic() + WAIT_S):
            case InstallStarted(version=version):
                print(f"Installed; the affected programs are running. Undo restores version {version[:12]}.", flush=True)
            case InstallRefused(reason=reason):
                raise SystemExit(reason)
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-receipt", type=Path, required=True)
    receipt = parser.parse_args().check_receipt
    if not isinstance(receipt, Path):
        parser.error("--check-receipt names the receipt file")
    if sys.platform != "win32":
        parser.error("Deploy from Windows with Dev.cmd deploy.")
    deploy(receipt, LIVE)


if __name__ == "__main__":
    main()
