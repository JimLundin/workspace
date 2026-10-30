"""Windows effects for a fresh source-only Workspace release.

Runtime folders are read and verified, never replaced or written by this helper.
Only the normal assistant WM_CLOSE contract is used. No process is terminated.
"""

import contextlib
import ctypes
import json
import os
import shutil
import stat
import subprocess
import time
import traceback
import zipfile
from collections.abc import Generator, Mapping
from ctypes import wintypes
from pathlib import Path, PurePosixPath
lazy import msvcrt

from components import ASSISTANT, BAR_WINDOW, CATALOGUE, LAYOUT, Writer, read_marker, shutdown_budget, unix_ms
from keeper_control import CAPABILITY, STATUS, Pause, Paused, Refused, Resume, Resumed, submit
from scripts.deploy_archive import repack
from scripts.deploy_files import PINS, RUNTIME, file_at, files, no_link, read, sha, write, zip_files
from scripts.deploy_policy import ComponentRestart, FullRestart, RestartPlan, restart_plan
from scripts.deploy_processes import Process, inventory, same_processes
from scripts.deploy_values import PREPARED, RELOADED, RUNTIME_AUDIT, STOPPED, Config, Exit, Prepared, Ready, Role, Stopped
from scripts.development_paths import PYTHON
lazy from winapi._core import fn

CORE = frozenset({"keeper", *CATALOGUE})
STOP_SLACK_S = 10.0
"""Beyond the keeper's own stop budgets: its control polling and the coordinator's observation."""


def launch_interpreter(installed: Mapping[str, object], stopped: Stopped) -> Path:
    if installed.get("rolled_back") is True:
        # A verified before-image must restart with its observed interpreter.
        # This also avoids an old launcher handing off and changing keeper PID.
        for previous in stopped["processes_before"]:
            if previous["role"] == "keeper":
                return Path(previous["executable"])
        raise RuntimeError("A rollback has no observed keeper interpreter.")
    return PYTHON.with_name("pythonw.exe")


def group(rows: tuple[Process, ...]) -> dict[Role, Process]:
    core: dict[Role, Process] = {row.role: row for row in rows if row.role in CORE}
    if len([row for row in rows if row.role in CORE]) != len(CORE) or set(core) != set(CORE):
        raise RuntimeError("The installed keeper and its three children are not a complete group.")
    if any(row.parent_pid != core["keeper"].pid for role, row in core.items() if role != "keeper"):
        raise RuntimeError("The installed children do not belong to the inspected keeper.")
    owners = {row.pid for row in core.values()}
    pending = [row for row in rows if row.role not in CORE]
    while pending:
        attached = [row for row in pending if row.parent_pid in owners]
        if not attached:
            raise RuntimeError("An installed process is outside the inspected Workspace tree.")
        owners.update(row.pid for row in attached)
        pending = [row for row in pending if row not in attached]
    return core


class Release:
    __slots__ = (
        "_baseline",
        "_close_handle",
        "_window_visible",
        "archive",
        "config",
        "find_window",
        "image_name",
        "live",
        "open_process",
        "post_message",
        "process_exit",
        "process_id",
        "process_times",
        "profile",
        "stage",
        "state",
        "wait_process",
        "wanted",
        "window_owner",
    )

    def __init__(self, stage: Path, config: Config, wanted: dict[str, str]) -> None:
        self.stage, self.config, self.wanted = stage, config, wanted
        self.live = Path(config["live_windows"])
        self.archive = Path(config["archive_windows"])
        self.profile = Path(config["profile_windows"])
        self.state = self.profile / "keeper"
        if (
            os.name != "nt"
            or stage.drive.casefold() != "c:"
            or Path.cwd() != stage
            or self.live != Path(r"C:\Users\Jim.Lundin\Downloads\workspace-sdk\workspace")
            or self.archive != Path(r"C:\Users\Jim.Lundin\Downloads\workspace-sdk-python315-win64.zip")
            or self.profile != Path(r"C:\Users\Jim.Lundin\AppData\Local\workspace")
        ):
            raise RuntimeError("The release requires its C-drive cwd and exact reviewed installation/profile.")
        self._baseline: Prepared | None = None
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        user = ctypes.WinDLL("user32", use_last_error=True)
        self.open_process = fn(kernel, "OpenProcess", wintypes.HANDLE, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        self.process_id = fn(kernel, "GetProcessId", wintypes.DWORD, wintypes.HANDLE)
        self.image_name = fn(
            kernel, "QueryFullProcessImageNameW", wintypes.BOOL, wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)
        )
        self.process_times = fn(kernel, "GetProcessTimes", wintypes.BOOL, wintypes.HANDLE, *([ctypes.POINTER(wintypes.FILETIME)] * 4))
        self.wait_process = fn(kernel, "WaitForSingleObject", wintypes.DWORD, wintypes.HANDLE, wintypes.DWORD)
        self.process_exit = fn(kernel, "GetExitCodeProcess", wintypes.BOOL, wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        self._close_handle = fn(kernel, "CloseHandle", wintypes.BOOL, wintypes.HANDLE)
        self.find_window = fn(user, "FindWindowW", wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR)
        self.window_owner = fn(user, "GetWindowThreadProcessId", wintypes.DWORD, wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
        self._window_visible = fn(user, "IsWindowVisible", wintypes.BOOL, wintypes.HWND)
        self.post_message = fn(user, "PostMessageW", wintypes.BOOL, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

    def receipt(self, name: str, value: Mapping[str, object]) -> None:
        write(self.stage / name, dict(value, stage_id=self.stage.name))

    def close_handle(self, handle: int) -> None:
        """The release owns each retained native handle's lifetime."""
        self._close_handle(handle)

    def window_visible(self, handle: int) -> bool:
        """Adapt the native BOOL before assessing desktop readiness."""
        return bool(self._window_visible(handle))

    def announce(self, phase: str) -> None:
        observation: dict[str, str | float] = {"phase": phase, "at": time.time()}
        print(json.dumps(observation), flush=True)

    def inventory(self) -> tuple[Process, ...]:
        return inventory(self.live)

    def footprint(self, name: str, rows: tuple[Process, ...], *, workload: str) -> None:
        if rows:
            group(rows)
        observations = [process_observation(row) for row in rows]
        self.receipt(
            name, {"observed_at_ns": time.time_ns(), "workload": workload, "processes": observations, "deployment_observer_excluded_pid": os.getpid()}
        )

    def hwnd(self, title: str, window_class: str | None = None) -> tuple[int, int]:
        handle = self.find_window(window_class, title)
        pid = wintypes.DWORD()
        if handle:
            self.window_owner(handle, ctypes.byref(pid))
        return int(handle or 0), pid.value

    def opened(self, row: Process) -> int:
        handle = self.open_process(0x1000 | 0x100000, False, row.pid)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            image = ctypes.create_unicode_buffer(32768)
            size = wintypes.DWORD(len(image))
            times = [wintypes.FILETIME() for _ in range(4)]
            if not self.image_name(handle, 0, image, ctypes.byref(size)) or not self.process_times(handle, *(ctypes.byref(value) for value in times)):
                raise ctypes.WinError(ctypes.get_last_error())
            created = unix_ms(times[0])
            if self.process_id(handle) != row.pid or Path(image.value) != Path(row.executable) or created != row.created_ms:
                raise RuntimeError("A process changed identity before its handle could be retained.")
            return handle
        except BaseException:
            self.close_handle(handle)
            raise

    def exit_code(self, handle: int) -> int | None:
        status = self.wait_process(handle, 0)
        if status == 258:
            return None
        if status != 0:
            raise ctypes.WinError(ctypes.get_last_error())
        code = wintypes.DWORD()
        if not self.process_exit(handle, ctypes.byref(code)):
            raise ctypes.WinError(ctypes.get_last_error())
        return code.value

    def pins(self) -> None:
        if any(sha(file_at(self.live, name)) != self.config["pins"][name] for name in PINS):
            raise RuntimeError("A runtime pin changed: source-only deployment must stop and the bundle workflow must rebuild.")

    def keeper_idle(self) -> None:
        recovery = self.state / "recovery.json"
        requests = self.state / "requests"
        if (recovery.exists() and read(recovery).get("pending") is not False) or (requests.exists() and any(requests.iterdir())):
            raise RuntimeError("The keeper has a pending update/trial or request; defer source deployment.")

    def runtime(self, expected: dict[str, str]) -> None:
        for folder in sorted(RUNTIME):
            inside = {name[len(folder) + 1 :]: value for name, value in expected.items() if name.startswith(folder + "/")}
            if not inside or files(self.live / folder, ignore_extra_bytecode=True, expected=inside) != inside:
                raise RuntimeError("Installed runtime membership or bytes differ from the unchanged bundle baseline.")

    def prepared(self) -> Prepared:
        # A single native coordinator owns this release. Source/archive validation
        # is done before close and after launch, rather than at every transition.
        if self._baseline is None:
            self.pins()
            baseline = PREPARED.validate_json((self.stage / "prepared.json").read_bytes(), strict=True)
            if (
                baseline["stage_id"] != self.stage.name
                or baseline["manifest_sha256"] != sha(self.stage / "source.json")
                or files(self.stage / "source") != self.wanted
            ):
                raise RuntimeError("The prepared source release changed.")
            self._baseline = baseline
        return self._baseline

    def runtime_fingerprint(self, expected: dict[str, str]) -> dict[str, list[int]]:
        result: dict[str, list[int]] = {}
        for folder in sorted(RUNTIME):
            root = self.live / folder
            no_link(root)
            pending = [root]
            while pending:
                directory = pending.pop()
                with os.scandir(directory) as entries:
                    for entry in entries:
                        observed = entry.stat(follow_symlinks=False)
                        if stat.S_ISLNK(observed.st_mode) or (os.name == "nt" and observed.st_file_attributes & 0x400):
                            raise ValueError("Runtime metadata contains a link or junction.")
                        path = Path(entry.path)
                        if stat.S_ISDIR(observed.st_mode):
                            pending.append(path)
                        elif stat.S_ISREG(observed.st_mode):
                            relative = path.relative_to(self.live).as_posix()
                            if ("__pycache__" in path.parts or path.suffix in (".pyc", ".pyo")) and relative not in expected:
                                continue
                            # Windows supplies these in the directory enumeration.
                            # File IDs would open every file; root IDs are verified separately.
                            result[relative] = [observed.st_size, observed.st_mtime_ns, observed.st_ctime_ns]
                        else:
                            raise ValueError("Runtime metadata contains a nonregular file.")
        return result

    def shutdown_receipt(self) -> Stopped:
        value = STOPPED.validate_json((self.stage / "stopped.json").read_bytes(), strict=True)
        if value.get("stage_id") != self.stage.name or value.get("clean_exit") is not True or type(value.get("was_running")) is not bool:
            raise RuntimeError("The release has no valid normal clean shutdown receipt.")
        if value["was_running"]:
            exits = [item for item in value.get("exits", []) if item.get("role") in CORE]
            preserved = value.get("preserved", [])
            retained_roles = {item["role"] for item in preserved if item["role"] in CORE}
            if (
                len(exits) != len(CORE - retained_roles)
                or frozenset(item["role"] for item in exits) != CORE - retained_roles
                or any(type(item.get("exit_code")) is not int or item["exit_code"] != 0 for item in exits)
            ):
                raise RuntimeError("The shutdown receipt does not prove clean exits for every replaced core process.")
            if preserved and (
                "keeper" not in retained_roles
                or any(item not in value["processes_before"] for item in preserved)
                or len({item["pid"] for item in preserved}) != len(preserved)
            ):
                raise RuntimeError("The partial shutdown receipt has invalid retained process identities.")
        elif value.get("processes_before") != [] or value.get("exits") != []:
            raise RuntimeError("An originally stopped copy has conflicting process evidence.")
        return value

    def prepare(self) -> None:
        self.announce("prepare checked source, backups and compressed runtime records while running")
        self.pins()
        if (self.stage / "prepared.json").exists():
            raise RuntimeError("Use a fresh release stage; preparation is never resumed implicitly.")
        payload = self.stage / "source.zip"
        if sha(payload) != self.config["payload_sha256"] or zip_files(payload) != self.wanted:
            raise RuntimeError("The transferred source ZIP differs from the checked manifest.")
        no_link(self.archive)
        old_archive_sha = sha(self.archive)
        cache_path = self.profile / "deployment" / "runtime-audit.json"
        cache = RUNTIME_AUDIT.validate_json(cache_path.read_bytes(), strict=True) if cache_path.exists() else None
        cached_runtime = cache["runtime"] if cache is not None else {}
        fingerprint = self.runtime_fingerprint(cached_runtime)
        cached = (
            cache is not None
            and cache["archive_sha256"] == old_archive_sha
            and bool(cached_runtime)
            and {name: values[-3:] for name, values in cache["fingerprint"].items()} == fingerprint
        )
        if cached:
            runtime = cached_runtime
            old_source = zip_files(self.archive, source_only=True)
        else:
            old = zip_files(self.archive)
            runtime = {name: value for name, value in old.items() if PurePosixPath(name).parts[0] in RUNTIME}
            old_source = {name: value for name, value in old.items() if name not in runtime}
            self.runtime(runtime)
            fingerprint = self.runtime_fingerprint(runtime)
        if any(old_source.get(name) != self.config["pins"][name] for name in PINS):
            raise RuntimeError("The installed archive runtime pins differ from the checked source.")
        source = self.stage / "source"
        source.mkdir()
        extract_source(payload, source, self.wanted)
        if files(source) != self.wanted:
            raise RuntimeError("The extracted source differs from the checked manifest.")
        existing = files(self.live, skip_roots=RUNTIME, ignore_extra_bytecode=True)
        # The retired private interpreter is managed removal, including locally
        # added files. Verified before-images allow the ordinary rollback path.
        old_source |= {name: value for name, value in existing.items() if name.startswith(".python/")}
        for name in self.wanted.keys() - old_source.keys():
            if name in existing and existing[name] != self.wanted[name]:
                raise RuntimeError("New source would overwrite an unrelated installed file.")
        unrelated = {name: value for name, value in existing.items() if name not in old_source and name not in self.wanted}
        output = self.stage / "new-bundle.zip"
        repack(self.archive, output, source, self.wanted)
        if zip_files(output, source_only=True) != self.wanted or sha(self.archive) != old_archive_sha:
            raise RuntimeError("The new ZIP source differs or the prior bundle changed during preparation.")
        # Full verified before-images are built while the client remains available.
        self.backup_source(existing, old_archive_sha)
        if self.runtime_fingerprint(runtime) != fingerprint:
            raise RuntimeError("The runtime changed during preparation.")
        self.receipt("backup.json", {"source": existing, "zip_sha256": old_archive_sha, "verified_at_ns": time.time_ns()})
        self.receipt(
            "prepared.json",
            {
                "manifest_sha256": sha(self.stage / "source.json"),
                "old_archive_sha256": old_archive_sha,
                "new_archive_sha256": sha(output),
                "runtime": runtime,
                "runtime_fingerprint": fingerprint,
                "runtime_audit_reused": bool(cached),
                "old_source": old_source,
                "source_before": existing,
                "unrelated_source": unrelated,
                "runtime_directory_ids": {name: [os.stat(self.live / name).st_dev, os.stat(self.live / name).st_ino] for name in RUNTIME},
                "prepared_at_ns": time.time_ns(),
            },
        )
        self.prepared()

    def backup_source(self, existing: Mapping[str, str], old_archive_sha: str) -> None:
        backup = self.stage / "backup"
        source_backup = backup / "source"
        source_backup.mkdir(parents=True)
        for name in existing:
            target = file_at(source_backup, name)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(file_at(self.live, name), target)
        shutil.copyfile(self.archive, backup / "previous-bundle.zip")
        if files(source_backup) != existing or sha(backup / "previous-bundle.zip") != old_archive_sha:
            raise RuntimeError("Source or ZIP before-images did not verify.")

    def stop(self) -> None:
        self.prepared()
        if not self.may_stop():
            return
        rows = self.inventory()
        if not rows:
            self.footprint("footprint-before.json", rows, workload="Workspace was already stopped")
            self.receipt("stopped.json", {"was_running": False, "clean_exit": True, "processes_before": [], "exits": []})
            return
        core = group(rows)
        plan = self.plan(core["keeper"].pid)
        match plan:
            case ComponentRestart():
                self.stop_selected(rows, plan)
            case FullRestart.ALL:
                self.stop_full(rows)

    def stop_full(self, rows: tuple[Process, ...]) -> None:
        core = group(rows)
        handle, owner = self.hwnd(ASSISTANT.window.title, ASSISTANT.window.window_class)
        if not handle or owner != core["assistant"].pid:
            raise RuntimeError("The installed assistant has no matching owned control window.")
        bar, bar_owner = self.hwnd(BAR_WINDOW)
        record: Stopped = {
            "was_running": True,
            "clean_exit": False,
            "processes_before": [row.identity() for row in rows],
            "bar_was_visible": bool(bar and bar_owner == owner and self.window_visible(bar)),
            "exits": [],
        }
        retained: dict[int, tuple[Process, int]] = {}
        try:
            with contextlib.ExitStack() as cleanup:
                for row in rows:
                    native = self.opened(row)
                    retained[row.pid] = (row, native)
                    cleanup.callback(self.close_handle, native)
                    if self.exit_code(native) is not None:
                        raise RuntimeError("The inspected process group changed before shutdown.")
                fresh = self.inventory()
                if [row.identity() for row in fresh] != [row.identity() for row in rows]:
                    raise RuntimeError("The process tree changed before the close request.")
                self.footprint("footprint-before.json", fresh, workload="Observed running installation immediately before WM_CLOSE")
                self.keeper_idle()
                record["requested_at_ns"] = time.time_ns()
                self.receipt("stop-started.json", record)
                if not self.post_message(handle, ASSISTANT.quit_message, 0, 0):
                    raise ctypes.WinError(ctypes.get_last_error())
                seen: set[int] = set()
                budget = shutdown_budget(CATALOGUE) + STOP_SLACK_S
                deadline = time.monotonic() + budget
                while True:
                    self.observe_exits(record, retained, seen)
                    remaining = self.inventory()
                    if any(row.role in CORE and row.identity() != core[row.role].identity() for row in remaining):
                        raise RuntimeError("The keeper replaced a core process during shutdown; installation is blocked.")
                    self.retain_arrivals(remaining, retained, cleanup, record)
                    if not remaining:
                        if len(seen) != len(retained):
                            continue
                        record["clean_exit"] = True
                        record["completed_at_ns"] = time.time_ns()
                        self.receipt("stopped.json", record)
                        return
                    if time.monotonic() >= deadline:
                        raise TimeoutError(f"Normal shutdown exceeded {budget:.0f} seconds; no process was terminated and no source was replaced.")
                    time.sleep(0.25)
        except Exception as error:
            self.receipt("stop-failure.json", dict(record, error_type=type(error).__name__, error=str(error)))
            raise

    def plan(self, keeper_pid: int) -> RestartPlan:
        baseline = self.prepared()
        # Unmanaged files are preserved, not removed by this release. Their
        # absence from the checked manifest cannot select a component restart.
        previous = frozendict((name, value) for name, value in baseline["source_before"].items() if name in baseline["old_source"])
        plan = restart_plan(self.stage / "backup" / "source", self.stage / "source", (previous, self.wanted))
        capability = self.state / "component-capability.json"
        supported = capability.is_file() and CAPABILITY.validate_json(capability.read_bytes(), strict=True).keeper_pid == keeper_pid
        result = plan if supported else FullRestart.ALL
        match result:
            case ComponentRestart(components=components):
                self.receipt("restart-plan.json", {"components": components, "full": False})
            case FullRestart.ALL:
                self.receipt("restart-plan.json", {"components": tuple(CATALOGUE), "full": True})
        return result

    def stop_selected(self, rows: tuple[Process, ...], plan: ComponentRestart) -> None:
        """Retain exact handles while the supervisor pauses selected child trees."""
        core = group(rows)
        selected = {row.pid for row in rows if row.role in plan.components}
        while descendants := {row.pid for row in rows if row.parent_pid in selected} - selected:
            selected.update(descendants)
        preserved = tuple(row for row in rows if row.pid not in selected)
        bar, owner = self.hwnd(BAR_WINDOW)
        record: Stopped = {
            "was_running": True,
            "clean_exit": False,
            "processes_before": [row.identity() for row in rows],
            "preserved": [row.identity() for row in preserved],
            "bar_was_visible": bool(bar and owner == core["assistant"].pid and self.window_visible(bar)),
            "exits": [],
        }
        retained: dict[int, tuple[Process, int]] = {}
        try:
            with contextlib.ExitStack() as cleanup:
                for row in rows:
                    handle = self.opened(row)
                    retained[row.pid] = row, handle
                    cleanup.callback(self.close_handle, handle)
                    if self.exit_code(handle) is not None:
                        raise RuntimeError("A component exited before the pause request.")
                if not same_processes(self.inventory(), rows):
                    raise RuntimeError("The process tree changed before component pause.")
                self.keeper_idle()
                self.footprint("footprint-before.json", rows, workload="Installation before selective component pause")
                record["requested_at_ns"] = time.time_ns()
                self.receipt("stop-started.json", record)
                submit(self.state, Pause(self.stage.name, plan.components))
                seen: set[int] = set()
                budget = shutdown_budget(plan.components) + STOP_SLACK_S
                deadline = time.monotonic() + budget
                while time.monotonic() < deadline:
                    if any(self.exit_code(retained[row.pid][1]) is not None for row in preserved):
                        raise RuntimeError("A retained component exited during source deployment.")
                    remaining = self.inventory()
                    if any(not any(row.identity() == original.identity() for original in rows) for row in remaining):
                        raise RuntimeError("The installed process tree changed during component pause.")
                    self.observe_exits(record, {pid: value for pid, value in retained.items() if pid in selected}, seen)
                    status = self.component_status()
                    match status:
                        case Refused(reason=reason):
                            raise RuntimeError("Component pause refused: " + reason)
                        case Paused(components=components) if (
                            components == plan.components and same_processes(remaining, preserved) and seen == selected
                        ):
                            record["clean_exit"] = True
                            record["completed_at_ns"] = time.time_ns()
                            self.receipt("stopped.json", record)
                            return
                        case _:
                            pass
                    time.sleep(0.1)
                raise TimeoutError(f"Component pause did not complete within {budget:.0f} seconds; no source was replaced.")
        except Exception as error:
            self.receipt("stop-failure.json", dict(record, error_type=type(error).__name__, error=str(error)))
            raise

    def component_status(self) -> Paused | Resumed | Refused | None:
        path = self.state / "component-status.json"
        if not path.is_file():
            return None
        try:
            status = STATUS.validate_json(path.read_bytes(), strict=True)
        except FileNotFoundError, PermissionError:
            return None
        return status if status.token == self.stage.name else None

    def retained_inventory(self, stopped: Stopped) -> tuple[Process, ...]:
        rows = self.inventory()
        if [row.identity() for row in rows] != stopped.get("preserved", []):
            raise RuntimeError("Processes changed after their recorded clean stop or component pause.")
        return rows

    def retain_arrivals(
        self,
        rows: tuple[Process, ...],
        retained: dict[int, tuple[Process, int]],
        cleanup: contextlib.ExitStack,
        record: Stopped,
    ) -> None:
        """Keep new handles in the same close transaction and cleanup lifetime.

        Rows, retained identities, cleanup and progress receipt are independently
        required to prove a clean stop while native children finish spawning.
        """
        for row in rows:
            if row.pid not in retained:
                try:
                    native = self.opened(row)
                except OSError:
                    if row.role == "runtime" and all(item.identity() != row.identity() for item in self.inventory()):
                        record.setdefault("transient_exits", []).append(dict[str, object](row.identity(), disappeared_before_handle=True))
                        continue
                    raise
                retained[row.pid] = (row, native)
                cleanup.callback(self.close_handle, native)

    def may_stop(self) -> bool:
        if (self.stage / "stopped.json").exists():
            self.retained_inventory(self.shutdown_receipt())
            return False
        if (self.stage / "stop-started.json").exists():
            raise RuntimeError("A prior close attempt needs review; this helper never retries it automatically.")
        return True

    def observe_exits(self, record: Stopped, retained: Mapping[int, tuple[Process, int]], seen: set[int]) -> None:
        """The stop transaction owns receipt accumulation while handles stay retained."""
        for pid, (row, native) in retained.items():
            code = self.exit_code(native)
            if code is not None and pid not in seen:
                seen.add(pid)
                record["exits"].append(Exit(**row.identity(), exit_code=code, observed_at_ns=time.time_ns()))
                self.receipt("stop-progress.json", record)
                if row.role in CORE and code != 0:
                    raise RuntimeError("A core Workspace process did not exit cleanly; no source replacement is allowed.")

    @contextlib.contextmanager
    def exclusive(self) -> Generator[None]:
        stopped = self.shutdown_receipt()
        retained_roles = {row["role"] for row in stopped.get("preserved", [])}
        with contextlib.ExitStack() as cleanup:
            for role, path in (("keeper", self.state / "keeper.lock"), ("automation", self.profile / "work" / "worker.lock")):
                if role in retained_roles:
                    continue
                path.parent.mkdir(parents=True, exist_ok=True)
                stream = cleanup.enter_context(path.open("r+b" if path.exists() else "w+b"))
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            self.retained_inventory(stopped)
            yield
            self.retained_inventory(stopped)

    def copy(self, source: Path, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(destination.name + "." + self.stage.name + ".pending")
        shutil.copyfile(source, temporary)
        if sha(temporary) != sha(source):
            raise RuntimeError("An atomic source/ZIP copy changed bytes.")
        os.replace(temporary, destination)

    def clear_bytecode(self, changed: set[str]) -> None:
        for name in changed:
            path = file_at(self.live, name)
            if path.suffix.casefold() not in (".py", ".pyw"):
                continue
            cache = path.parent / "__pycache__"
            if cache.exists():
                no_link(cache)
                for compiled in cache.glob(path.stem + ".*.pyc"):
                    no_link(compiled)
                    compiled.unlink()
            for suffix in (".pyc", ".pyo"):
                compiled = path.with_suffix(suffix)
                if compiled.exists() or compiled.is_symlink():
                    no_link(compiled)
                    compiled.unlink()

    def verify_files(self, baseline: Prepared) -> None:
        actual = files(self.live, skip_roots=RUNTIME, ignore_extra_bytecode=True)
        if actual != self.wanted | baseline["unrelated_source"]:
            raise RuntimeError("Installed source or preserved unrelated files differ from the checked release.")
        for name, expected in baseline["runtime_directory_ids"].items():
            observed = os.stat(self.live / name)
            if [observed.st_dev, observed.st_ino] != expected:
                raise RuntimeError("A preserved runtime directory was replaced.")
        if self.runtime_fingerprint(baseline["runtime"]) != baseline["runtime_fingerprint"]:
            raise RuntimeError("Preserved runtime membership or metadata changed after its byte audit.")
        if sha(self.archive) != baseline["new_archive_sha256"] or zip_files(self.archive, source_only=True) != self.wanted:
            raise RuntimeError("The Downloads ZIP differs from the checked source and preserved compressed runtime records.")

    def install(self) -> None:
        self.announce("back up and replace managed source only")
        baseline = self.prepared()
        self.shutdown_receipt()
        if (self.stage / "installation-started.json").exists():
            raise RuntimeError("Installation already started; inspect its preserved backups before another action.")
        with self.exclusive():
            self.pins()
            no_link(self.archive)
            if files(self.live, skip_roots=RUNTIME, ignore_extra_bytecode=True) != baseline["source_before"]:
                raise RuntimeError("Installed source or ZIP changed after release preparation.")
            if self.runtime_fingerprint(baseline["runtime"]) != baseline["runtime_fingerprint"]:
                raise RuntimeError("The runtime changed after preparation.")
            changed = {name for name, value in self.wanted.items() if baseline["source_before"].get(name) != value}
            removed = baseline["old_source"].keys() - self.wanted.keys()
            self.receipt("installation-started.json", {"started_at_ns": time.time_ns(), "changed": sorted(changed), "removed": sorted(removed)})
            for name in removed:
                file_at(self.live, name).unlink(missing_ok=True)
            for name in changed:
                self.copy(self.stage / "source" / name, file_at(self.live, name))
            self.clear_bytecode(changed | removed)
            retired = self.live / ".python"
            if retired.exists():
                shutil.rmtree(retired)
            if files(self.live, skip_roots=RUNTIME, ignore_extra_bytecode=True) != self.wanted | baseline["unrelated_source"]:
                raise RuntimeError("Installed source differs from the checked release.")
            self.receipt(
                "installed.json",
                {
                    "installed_at_ns": time.time_ns(),
                    "source_files": len(self.wanted),
                    "zip_pending": True,
                    "runtime_folders_preserved": sorted(RUNTIME),
                },
            )

    def publish_archive(self, baseline: Prepared) -> None:
        observed = sha(self.archive)
        if observed == baseline["new_archive_sha256"]:
            return
        if observed != baseline["old_archive_sha256"]:
            raise RuntimeError("The Downloads ZIP changed outside this deployment; it will not be overwritten.")
        candidate = self.stage / "new-bundle.zip"
        no_link(candidate)
        no_link(self.archive)
        if sha(candidate) != baseline["new_archive_sha256"]:
            raise RuntimeError("The prepared ZIP changed after verification.")
        os.replace(candidate, self.archive)
        self.receipt("archive-published.json", {"published_at_ns": time.time_ns(), "zip_sha256": baseline["new_archive_sha256"]})

    def restore_before_launch(self) -> None:
        baseline = self.prepared()
        self.shutdown_receipt()
        if (self.stage / "launch.json").exists():
            raise RuntimeError("A launch was attempted; live failure recovery needs inspection.")
        source = self.stage / "backup" / "source"
        archive = self.stage / "backup" / "previous-bundle.zip"
        if files(source) != baseline["source_before"] or sha(archive) != baseline["old_archive_sha256"]:
            raise RuntimeError("Rollback before-images changed.")
        with self.exclusive():
            changed = {name for name, value in self.wanted.items() if value != baseline["source_before"].get(name)} | (
                baseline["old_source"].keys() - self.wanted.keys()
            )
            for name in changed - baseline["source_before"].keys():
                file_at(self.live, name).unlink(missing_ok=True)
            for name in changed & baseline["source_before"].keys():
                self.copy(file_at(source, name), file_at(self.live, name))
            self.clear_bytecode(changed)
            self.copy(archive, self.archive)
            if files(self.live, skip_roots=RUNTIME, ignore_extra_bytecode=True) != baseline["source_before"]:
                raise RuntimeError("Restored source did not verify.")
        self.receipt(
            "rollback.json", {"restored_at_ns": time.time_ns(), "source": baseline["source_before"], "zip_sha256": baseline["old_archive_sha256"]}
        )
        self.receipt("installed.json", {"rolled_back": True})
        self.reload()

    def readiness(self, keeper_pid: int, started_ns: int, *, require_bar: bool) -> tuple[Ready, tuple[Process, ...]] | None:
        rows = self.inventory()
        try:
            core = group(rows)
        except RuntimeError:
            return None
        stopped = self.shutdown_receipt()
        preserved = {row["role"]: row for row in stopped.get("preserved", []) if row["role"] in CORE}
        if core["keeper"].pid != keeper_pid or any(
            row.identity() != preserved[role] if role in preserved else row.created_ms < started_ns // 1000000 for role, row in core.items()
        ):
            return None
        if any(read_marker(entry.marker(self.state)) != Writer(core[name].pid, core[name].created_ms) for name, entry in CATALOGUE.items()):
            return None
        control, owner = self.hwnd(ASSISTANT.window.title, ASSISTANT.window.window_class)
        if not control or owner != core["assistant"].pid:
            return None
        if require_bar:
            bar, bar_owner = self.hwnd(BAR_WINDOW)
            if not bar or bar_owner != owner or not self.window_visible(bar):
                return None
        return {"core": {role: row.identity() for role, row in core.items()}}, rows

    def reload(self) -> None:
        self.prepared()
        installed = read(self.stage / "installed.json")
        if installed.get("stage_id") != self.stage.name or (self.stage / "launch.json").exists():
            raise RuntimeError("This source release is not installed or a relaunch was already attempted.")
        stopped = self.shutdown_receipt()
        retained = self.retained_inventory(stopped)
        if not stopped["was_running"]:
            self.footprint("footprint-after.json", (), workload="Workspace was left stopped as originally observed")
            self.receipt("reloaded.json", {"was_running": False, "left_stopped": True})
            return
        if retained:
            keeper_pid = next(row.pid for row in retained if row.role == "keeper")
            started_ns = time.time_ns()
            self.receipt("launch.json", {"keeper_pid": keeper_pid, "started_at_ns": started_ns, "preserved": stopped.get("preserved", [])})
            submit(self.state, Resume(self.stage.name))
            self.wait_ready(keeper_pid, started_ns)
            return
        environment = {key: value for key, value in os.environ.items() if key.upper() not in ("PYTHONPATH", "PYTHONHOME", "WORKSPACE_READY")}
        environment["LOCALAPPDATA"] = str(self.profile.parent)
        environment["WORKSPACE_LIFECYCLE_TRACE"] = str(self.stage / "lifecycle.jsonl")
        started_ns = time.time_ns()
        child = subprocess.Popen(
            [str(launch_interpreter(installed, stopped)), str(self.live / "workspace.pyw")],
            cwd=self.live,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
        )
        self.receipt("launch.json", {"keeper_pid": child.pid, "started_at_ns": started_ns})
        self.wait_ready(child.pid, started_ns)

    def wait_ready(self, keeper_pid: int, started_ns: int) -> None:
        stopped = self.shutdown_receipt()
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            if not any(row.pid == keeper_pid and row.role == "keeper" for row in self.inventory()):
                raise RuntimeError("The keeper exited before readiness.")
            if stopped.get("preserved"):
                status = self.component_status()
                match status:
                    case Refused(reason=reason):
                        raise RuntimeError("Component resume refused: " + reason)
                    case Resumed():
                        pass
                    case _:
                        time.sleep(0.1)
                        continue
            ready = self.readiness(keeper_pid, started_ns, require_bar=stopped.get("bar_was_visible", False))
            if ready is not None:
                time.sleep(0.5)
                stable = self.readiness(keeper_pid, started_ns, require_bar=stopped.get("bar_was_visible", False))
                if stable is None or stable[0] != ready[0]:
                    raise RuntimeError("Core child identities or readiness changed during the stability observation.")
                self.footprint("footprint-after.json", stable[1], workload="Relaunched installation after fresh readiness and initial core stability")
                self.receipt(
                    "reloaded.json",
                    {"was_running": True, "started_at_ns": started_ns, "keeper_pid": keeper_pid, **stable[0], "verified_at_ns": time.time_ns()},
                )
                return
            time.sleep(0.5)
        raise TimeoutError("Fresh readiness did not complete within 90 seconds; the failed reload is recorded.")

    def verify(self) -> None:
        baseline = self.prepared()
        self.publish_archive(baseline)
        self.verify_files(baseline)
        reloaded, stopped = RELOADED.validate_json((self.stage / "reloaded.json").read_bytes(), strict=True), self.shutdown_receipt()
        if reloaded["was_running"] is True:
            ready = self.readiness(reloaded["keeper_pid"], reloaded["started_at_ns"], require_bar=stopped.get("bar_was_visible", False))
            if ready is None or ready[0]["core"] != reloaded["core"]:
                raise RuntimeError("Reloaded core processes or readiness no longer match the verified launch.")
        elif self.inventory():
            raise RuntimeError("An originally stopped copy unexpectedly started.")
        cache_path = self.profile / "deployment" / "runtime-audit.json"
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        write(cache_path.parent / "source.json", {"files": self.wanted})
        write(
            cache_path,
            {
                "runtime": baseline["runtime"],
                "fingerprint": baseline["runtime_fingerprint"],
                "archive_sha256": baseline["new_archive_sha256"],
                "verified_stage": self.stage.name,
            },
        )
        self.receipt(
            "verified.json",
            {
                "verified_at_ns": time.time_ns(),
                "source_files": len(self.wanted),
                "zip_sha256": baseline["new_archive_sha256"],
                "runtime_folders_preserved": sorted(RUNTIME),
                "was_running": stopped["was_running"],
            },
        )


def drive(release: Release, action: str) -> None:
    stage = release.stage
    measurements: dict[str, float] = {}
    started = time.perf_counter()
    try:
        if action == "deploy":
            for label, operation in (
                ("prepare", release.prepare),
                ("stop", release.stop),
                ("install", release.install),
                ("reload", release.reload),
                ("verify", release.verify),
            ):
                tick = time.perf_counter()
                operation()
                measurements[label] = round(time.perf_counter() - tick, 3)
                release.announce(f"{label} complete in {measurements[label]:.3f}s")
            measurements["total"] = round(time.perf_counter() - started, 3)
            stopped = STOPPED.validate_json((stage / "stopped.json").read_bytes(), strict=True)
            if stopped["was_running"]:
                reloaded = RELOADED.validate_json((stage / "reloaded.json").read_bytes(), strict=True)
                match reloaded:
                    case {"was_running": True, "verified_at_ns": int() as verified}:
                        pass
                    case _:
                        raise RuntimeError("The reloaded receipt has no verified readiness time.")
                measurements["outage"] = round((verified - stopped.get("requested_at_ns", 0)) / 1e9, 3) if stopped["exits"] else 0.0
                measurements["keyboard_outage"] = (
                    0.0 if any(row["role"] == LAYOUT.name for row in stopped.get("preserved", [])) else measurements["outage"]
                )
            release.receipt("timings.json", measurements)
            print(json.dumps(measurements), flush=True)
        elif action == "verify":
            release.verify()
        else:
            raise ValueError("Unsupported release action.")
    except Exception as error:
        if (stage / "installation-started.json").exists() and not (stage / "launch.json").exists():
            try:
                release.restore_before_launch()
            except Exception:
                (stage / "rollback-failure.log").write_text(traceback.format_exc(), encoding="utf-8")
        path = stage / f"failure-{time.time_ns()}.log"
        path.write_text(traceback.format_exc(), encoding="utf-8")
        failure: dict[str, object] = {
            "failed_action": action,
            "error_type": type(error).__name__,
            "details": str(path),
            "backup": str(stage / "backup"),
            "timings": measurements,
        }
        print(json.dumps(failure), flush=True)
        raise


def run(action: str, stage: Path, config: Config, wanted: dict[str, str]) -> None:
    drive(Release(stage, config, wanted), action)


def extract_source(payload: Path, source: Path, wanted: Mapping[str, str]) -> None:
    with zipfile.ZipFile(payload) as archive:
        for name in wanted:
            target = file_at(source, name)
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open("workspace/" + name) as incoming, target.open("xb") as extracted:
                shutil.copyfileobj(incoming, extracted)


def process_observation(row: Process) -> dict[str, object]:
    return dict[str, object](
        row.identity(),
        private_bytes=row.private_bytes,
        working_set_bytes=row.working_set_bytes,
        user_cpu_100ns=row.user_cpu_100ns,
        kernel_cpu_100ns=row.kernel_cpu_100ns,
    )
