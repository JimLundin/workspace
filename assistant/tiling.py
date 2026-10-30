"""A separately installed GlazeWM, with bounded commands and explicit process ownership."""

import json
import os
import subprocess
import threading
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol, cast
from uuid import UUID

from usage import DIRECTORY
lazy from winapi.processes import shell_start


class ManagedProcess(Protocol):
    pid: int

    def poll(self) -> int | None: ...
    def wait(self, timeout: float) -> int: ...
    def kill(self) -> None: ...


class ManagerRuntime(Protocol):
    """The manager's command transport, process lifetime and polling environment."""

    def run(self, arguments: Sequence[str]) -> subprocess.CompletedProcess[str]: ...
    def launch(self, arguments: Sequence[str]) -> ManagedProcess: ...
    def enabled(self) -> bool: ...
    def clock(self) -> float: ...
    def sleep(self, seconds: float) -> None: ...


class NativeRuntime:
    def run(self, arguments: Sequence[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            arguments, check=False, capture_output=True, text=True, encoding="utf-8", timeout=3, creationflags=0x08000000 if os.name == "nt" else 0
        )

    def launch(self, arguments: Sequence[str]) -> ManagedProcess:
        if os.name == "nt":
            return shell_start(list(arguments))
        return subprocess.Popen(arguments, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def enabled(self) -> bool:
        return os.environ.get("WORKSPACE_TILING", "on").lower() != "off"

    def clock(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


def reply(body: str) -> object:
    """GlazeWM can exit zero after a rejected command; its JSON result owns success."""
    try:
        value: object = json.loads(body)
    except ValueError as error:
        raise OSError("GlazeWM returned an invalid result.") from error
    if not isinstance(value, dict):
        raise OSError("GlazeWM returned an invalid result.")
    result = cast(dict[str, object], value)
    if result.get("success") is not True:
        problem = result.get("error")
        raise OSError(problem[:240] if isinstance(problem, str) else "GlazeWM could not complete the command.")
    return result.get("data")


def window_id(data: object, hwnd: int) -> str | None:
    """Resolve the captured native window, never whichever window a popup focused."""
    if not isinstance(data, dict):
        raise OSError("GlazeWM returned an invalid window list.")
    rows = cast(dict[str, object], data).get("windows")
    if not isinstance(rows, list):
        raise OSError("GlazeWM returned an invalid window list.")
    for row in cast(list[object], rows):
        if not isinstance(row, dict):
            raise OSError("GlazeWM returned an invalid window.")
        window = cast(dict[str, object], row)
        if type(window.get("handle")) is int and window["handle"] == hwnd:
            identity = window.get("id")
            if isinstance(identity, str):
                try:
                    return str(UUID(identity))
                except ValueError:
                    pass
            raise OSError("GlazeWM returned an invalid window identity.")
    return None


def window_handles(data: object) -> frozenset[int]:
    if not isinstance(data, dict):
        raise OSError("GlazeWM returned an invalid window list.")
    rows = cast(dict[str, object], data).get("windows")
    if not isinstance(rows, list):
        raise OSError("GlazeWM returned an invalid window list.")
    found: set[int] = set()
    for value in cast(list[object], rows):
        if not isinstance(value, dict):
            raise OSError("GlazeWM returned an invalid window.")
        handle = cast(dict[str, object], value).get("handle")
        if type(handle) is not int or handle <= 0:
            raise OSError("GlazeWM returned an invalid window handle.")
        found.add(handle)
    return frozenset(found)


def executable() -> Path:
    override = os.environ.get("WORKSPACE_GLAZEWM")
    return Path(override) if override else DIRECTORY / "tools" / "glazewm-v3.10.1" / "glazewm.exe"


def scoped_config(source: bytes) -> bytes:
    """Repair only Workspace's generated title-only ignore rule, preserving preferences."""
    for ending in (b"\r\n", b"\n"):
        for expression in (r"(?i)^workspace(?:\b| ·)", r"(?i)^(?:toolkit|workspace)(?:\b| ·)"):
            title = expression.encode()
            stanza = ending.join((b"  - commands: ['ignore']", b"    match:", b"      - window_title: { regex: '" + title + b"' }", b""))
            # Require a whole generated stanza at a line boundary. A following
            # nested field means this rule is already constrained/customized.
            start = source.find(stanza)
            if start < 0 or (start > 0 and source[start - 1 : start] != b"\n"):
                continue
            tail = source[start + len(stanza) :]
            following = next((line for line in tail.splitlines() if line.strip() and not line.lstrip().startswith(b"#")), b"")
            if following.startswith(b"        "):
                continue
            repaired = ending.join(
                (
                    b"  - commands: ['ignore']",
                    b"    match:",
                    "      - window_title: { regex: '(?i)^workspace(?:\\b| ·)' }".encode(),
                    b"        window_process: { regex: '^pythonw?$' }",
                    b"",
                )
            )
            return source[:start] + repaired + tail
    return source


class GlazeWM:
    __slots__ = ("binary", "cli", "closed", "config", "lock", "process", "runtime")

    def __init__(self, binary: Path | None = None, config: Path | None = None, *, runtime: ManagerRuntime | None = None) -> None:
        self.binary = binary or executable()
        self.cli = self.binary.parent / "cli" / "glazewm.exe"
        self.config = config or DIRECTORY / "glazewm.yaml"
        self.process: ManagedProcess | None = None
        self.lock = threading.RLock()
        self.closed = False
        self.runtime: ManagerRuntime = NativeRuntime() if runtime is None else runtime

    def available(self) -> bool:
        return self.binary.is_file() and self.cli.is_file()

    def exchange(self, args: Sequence[str]) -> object:
        if not self.available():
            raise OSError("GlazeWM isn't installed. See Workspace's tiling setup instructions.")
        try:
            result = self.runtime.run((str(self.cli), *args))
        except subprocess.TimeoutExpired as error:
            raise OSError("GlazeWM did not answer within three seconds.") from error
        if result.returncode:
            raise OSError("GlazeWM isn't responding. Restart automatic tiling from the Workspace menu.")
        return reply(result.stdout)

    def paused(self) -> bool | None:
        try:
            value = self.exchange(("query", "paused"))
            return value if type(value) is bool else None
        except OSError, ValueError:
            return None

    def start(self) -> None:
        with self.lock:
            if self.closed or not self.runtime.enabled() or not self.available():
                return
            if self.paused() is not None:
                return  # An existing manager is borrowed; preserve its config and lifetime.
            self._stop_owned()
            if not self.config.exists():
                self.config.parent.mkdir(parents=True, exist_ok=True)
                self.config.write_bytes(Path(__file__).with_name("glazewm.yaml").read_bytes())
            else:
                original = self.config.read_bytes()
                configured = scoped_config(original)
                if configured != original:
                    self.config.write_bytes(configured)
            try:
                self.process = self.runtime.launch((str(self.binary), "start", "--config", str(self.config)))
                deadline = self.runtime.clock() + 8
                while self.process.poll() is None and self.runtime.clock() < deadline:
                    if self.paused() is not None:
                        return
                    self.runtime.sleep(0.1)
                raise OSError("GlazeWM could not start. See %USERPROFILE%\\.glzr\\glazewm\\errors.log.")
            except BaseException:
                self._stop_owned()
                raise

    def command(self, args: Sequence[str], hwnd: int | None = None) -> None:
        with self.lock:
            if self.closed:
                return
            if self.paused() is None:
                self.start()
            if self.paused() is True and tuple(args) != ("wm-toggle-pause",):
                raise OSError("Automatic tiling is paused. Resume it from Window tiling in the bar menu.")
            subject: tuple[str, ...] = ()
            if hwnd is not None:
                identity = window_id(self.exchange(("query", "windows")), hwnd)
                if identity is None:
                    raise OSError("This window isn't managed by automatic tiling.")
                subject = ("--id", identity)
            self.exchange(("command", *subject, *args))

    def arrange(self, args: Sequence[str], hwnd: int) -> bool:
        """Adapt existing snap actions when tiling is active, with a native fallback."""
        with self.lock:
            if self.closed or self.paused() is not False:
                return False
            identity = window_id(self.exchange(("query", "windows")), hwnd)
            if identity is None:
                return False
            self.exchange(("command", "--id", identity, *args))
            return True

    def focus(self, hwnd: int) -> bool:
        """Reveal a managed window's workspace before focusing the exact container."""
        with self.lock:
            if self.closed or self.paused() is not False:
                return False
            identity = window_id(self.exchange(("query", "windows")), hwnd)
            if identity is None:
                return False
            self.exchange(("command", "focus", "--container-id", identity))
            return True

    def managed_handles(self) -> frozenset[int]:
        with self.lock:
            if self.closed or self.paused() is None:
                return frozenset()
            return window_handles(self.exchange(("query", "windows")))

    def _stop_owned(self) -> None:
        if self.process is not None:
            try:
                if self.process.poll() is None:
                    try:
                        if self.paused() is True:
                            self.exchange(("command", "wm-toggle-pause"))
                        self.exchange(("command", "wm-exit"))
                    except OSError, ValueError:
                        pass
                    try:
                        self.process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        self.process.kill()
                        self.process.wait(timeout=3)
            finally:
                self.process = None

    def close(self) -> None:
        with self.lock:
            if not self.closed:
                self.closed = True
                self._stop_owned()
