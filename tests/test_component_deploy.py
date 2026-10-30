"""Selective release behavior with real child processes and local source/ZIPs."""

import contextlib
import io
import os
from pathlib import Path

from keeper import Program
from scripts.deploy_files import read, sha
from scripts.deploy_policy import ComponentRestart
from scripts.deploy_windows import drive
from tests.component_deploy_fixture import ComponentRelease, SourceChange


def test_selective_deployment_and_rollback_preserve_keyboard_and_supervisor(tmp_path: Path) -> None:
    # Defects: the selective lane restarts retained children, accepts stale
    # readiness for a replacement, or resumes against a partial failed copy.
    for index, (change, fail) in enumerate(((SourceChange.ASSISTANT, False), (SourceChange.ASSISTANT, True), (SourceChange.UNCHANGED, False))):
        root = tmp_path / str(index)
        root.mkdir()
        release = ComponentRelease(root, change, fail_copy=fail)
        before = release.inventory()
        try:
            components: tuple[Program, ...] = ("assistant",) if change is SourceChange.ASSISTANT else ()
            assert release.plan(next(row.pid for row in before if row.role == "keeper")) == ComponentRestart(components)
            with contextlib.redirect_stdout(io.StringIO()):
                try:
                    drive(release, "deploy")
                except OSError as error:
                    assert fail and "injected replacement failure" in str(error)
                else:
                    assert not fail
            after = release.inventory()
            for original in before:
                current = next(row for row in after if row.role == original.role)
                if original.role == "assistant" and change is SourceChange.ASSISTANT:
                    assert current.pid != original.pid
                else:
                    assert current.identity() == original.identity()
            expected = "version = 'after'\n" if not fail and change is SourceChange.ASSISTANT else "version = 'before'\n"
            assert (release.state / "ready-assistant").read_text() == expected
            stopped = release.shutdown_receipt()
            assert [row["role"] for row in stopped["exits"]] == list(components)
            assert {row["role"] for row in stopped.get("preserved", [])} == {"keeper", "automation", "miryoku", "assistant"} - set(components)
            assert read(release.stage / "restart-plan.json")["components"] == list(components)
            assert (release.live / ".ruff_cache" / "CACHEDIR.TAG").read_bytes() == b"unmanaged cache bytes"
            if fail:
                assert (release.stage / "rollback.json").is_file()
                assert sha(release.archive) == release.baseline["old_archive_sha256"]
                assert not (release.live / "added.py").exists()
            elif change is SourceChange.ASSISTANT:
                assert (release.stage / "verified.json").is_file()
                # A retained marker can stay old, but the assistant's marker
                # must come from this launch rather than the previous process.
                launched = read(release.stage / "launch.json")
                match launched:
                    case {"keeper_pid": int() as pid, "started_at_ns": int() as started}:
                        pass
                    case _:
                        raise AssertionError("Missing launch evidence")
                marker = release.state / "ready-assistant"
                fresh = marker.stat().st_mtime_ns
                os.utime(marker, ns=(1, 1))
                assert release.readiness(pid, started, require_bar=True) is None
                os.utime(marker, ns=(fresh, fresh))
                assert release.readiness(pid, started, require_bar=True) is not None
            else:
                assert read(release.stage / "timings.json")["keyboard_outage"] == 0
        finally:
            release.close()
