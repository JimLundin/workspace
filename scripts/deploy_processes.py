"""Native process inventory: no PowerShell process per shutdown/readiness poll.

Command lines are classified inside this boundary and never included in receipts.
Process handles bind executable, creation time and exit status across PID reuse.
"""

import ctypes
import os
from collections.abc import Sequence
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

from components import CATALOGUE, unix_ms
from scripts.deploy_values import Identity, Role
from scripts.development_paths import USER
lazy from winapi._core import fn

INSTALLATION = PureWindowsPath(r"C:\Users\Jim.Lundin\Downloads\workspace-sdk\workspace")


@dataclass(frozen=True, slots=True)
class Process:
    pid: int
    parent_pid: int
    role: Role
    executable: str
    created_ms: int
    private_bytes: int | None = None
    working_set_bytes: int | None = None
    user_cpu_100ns: int | None = None
    kernel_cpu_100ns: int | None = None

    def identity(self) -> Identity:
        return {"pid": self.pid, "parent_pid": self.parent_pid, "role": self.role, "executable": self.executable, "created_ms": self.created_ms}


def same_processes(before: Sequence[Process], after: Sequence[Process]) -> bool:
    """Resource counters can change while each process retains its identity."""
    return len(before) == len(after) and all(left.identity() == right.identity() for left, right in zip(before, after, strict=True))


def role_for(arguments: tuple[str, ...], *, windowed: bool, editor: tuple[PureWindowsPath, PureWindowsPath] | None = None) -> Role | None:
    arguments = (arguments[0], *(value for value in arguments[1:] if value not in ("-B", "-u", "-s"))) if arguments else ()
    if editor is not None and arguments and PureWindowsPath(arguments[0]) == editor[0] and not windowed:
        # Development tools use a venv launcher sharing the installed base
        # interpreter. Their fresh checks/isolated views are separately owned
        # and must coexist with an ordinary source deployment.
        if len(arguments) >= 3 and arguments[1:3] in (("-m", "scripts.watch"), ("-m", "scripts.check"), ("-m", "scripts.preview")):
            return None
        editor_script = PureWindowsPath(arguments[1]) if len(arguments) == 2 else None
        if editor_script is not None and editor_script.is_relative_to(editor[1]):
            relative = editor_script.relative_to(editor[1]).parts
            if (
                len(relative) == 4
                and relative[0].casefold().startswith("ms-python.black-formatter-")
                and editor_script.as_posix().casefold().endswith("/bundled/tool/lsp_server.py")
            ):
                return None
    if len(arguments) >= 3 and arguments[1:3] == ("-m", "assistant.browser_host"):
        return None
    if windowed:
        if len(arguments) == 3 and arguments[1] == "-m":
            for entry in CATALOGUE.values():
                if arguments[2] == entry.module:
                    return entry.name
        if len(arguments) == 2 and Path(arguments[1]).name.casefold() in ("workspace.pyw", "keeper.py"):
            return "keeper"
    return "runtime"


class Entry(ctypes.Structure):
    dwSize: int
    th32ProcessID: int
    th32ParentProcessID: int
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


class UnicodeString(ctypes.Structure):
    Length: int
    MaximumLength: int
    Buffer: int | None
    _fields_ = [("Length", wintypes.USHORT), ("MaximumLength", wintypes.USHORT), ("Buffer", ctypes.c_void_p)]


@dataclass(frozen=True, slots=True)
class Observation:
    process: Process
    arguments: tuple[str, ...]


def installation_command(arguments: Sequence[str], live: PureWindowsPath) -> bool:
    match tuple(value for value in arguments[1:] if value not in ("-B", "-u", "-s")):
        case (script, *_) if not script.startswith("-"):
            return PureWindowsPath(script).is_relative_to(live)
        case _:
            return False


def installed_processes(observations: Sequence[Observation], live: PureWindowsPath) -> tuple[Process, ...]:
    """Bind shared-interpreter processes to the installed command and its descendants."""
    roots = frozenset(
        row.process.pid
        for row in observations
        if PureWindowsPath(row.process.executable).is_relative_to(live) or installation_command(row.arguments, live)
    )
    owned = roots
    while added := frozenset(row.process.pid for row in observations if row.process.parent_pid in owned) - owned:
        owned |= added
    return tuple(sorted((row.process for row in observations if row.process.pid in owned), key=process_id))


def inventory(live: Path) -> tuple[Process, ...]:
    reader = ProcessReader()
    snapshot = reader.snapshot_call(2, 0)
    if snapshot is None or snapshot == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    rows: list[Observation] = []
    try:
        entry = Entry()
        entry.dwSize = ctypes.sizeof(entry)
        more = reader.first(snapshot, ctypes.byref(entry))
        while more:
            row = reader.read(entry, live)
            if row is not None:
                rows.append(row)
            more = reader.next_entry(snapshot, ctypes.byref(entry))
        if ctypes.get_last_error() != 18:
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        reader.close(snapshot)
    return installed_processes(rows, PureWindowsPath(live))


def argument(value: object) -> str:
    match value:
        case str():
            return value
        case _:
            raise RuntimeError("Invalid native command-line argument.")


def process_id(row: Process) -> int:
    return row.pid


class ProcessReader:
    """One inventory owns its ABI bindings and each temporary process handle."""

    __slots__ = (
        "argument_pointer",
        "close",
        "first",
        "free",
        "image_name",
        "information",
        "next_entry",
        "open_process",
        "process_times",
        "snapshot_call",
    )

    def __init__(self) -> None:
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        nt = ctypes.WinDLL("ntdll")
        shell = ctypes.WinDLL("shell32", use_last_error=True)
        self.snapshot_call = fn(kernel, "CreateToolhelp32Snapshot", wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD)
        self.first = fn(kernel, "Process32FirstW", wintypes.BOOL, wintypes.HANDLE, ctypes.POINTER(Entry))
        self.next_entry = fn(kernel, "Process32NextW", wintypes.BOOL, wintypes.HANDLE, ctypes.POINTER(Entry))
        self.open_process = fn(kernel, "OpenProcess", wintypes.HANDLE, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        self.close = fn(kernel, "CloseHandle", wintypes.BOOL, wintypes.HANDLE)
        self.image_name = fn(
            kernel, "QueryFullProcessImageNameW", wintypes.BOOL, wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)
        )
        self.process_times = fn(kernel, "GetProcessTimes", wintypes.BOOL, wintypes.HANDLE, *([ctypes.POINTER(wintypes.FILETIME)] * 4))
        self.information = fn(
            nt,
            "NtQueryInformationProcess",
            wintypes.LONG,
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.ULONG,
            ctypes.POINTER(wintypes.ULONG),
        )
        self.argument_pointer = fn(shell, "CommandLineToArgvW", ctypes.c_void_p, wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int))
        self.free = fn(kernel, "LocalFree", ctypes.c_void_p, ctypes.c_void_p)

    def read(self, entry: Entry, live: Path) -> Observation | None:
        pid = entry.th32ProcessID
        handle = self.open_process(0x1000, False, pid) if pid and pid != os.getpid() else None
        if handle:
            try:
                image = ctypes.create_unicode_buffer(32768)
                size = wintypes.DWORD(len(image))
                if self.image_name(handle, 0, image, ctypes.byref(size)) and (
                    PureWindowsPath(image.value).name.casefold() in ("python.exe", "pythonw.exe")
                    or PureWindowsPath(image.value).is_relative_to(PureWindowsPath(live))
                ):
                    needed = wintypes.ULONG()
                    self.information(handle, 60, None, 0, ctypes.byref(needed))
                    if not ctypes.sizeof(UnicodeString) <= needed.value <= 1_000_000:
                        raise RuntimeError("Cannot inspect an installed process command line.")
                    buffer = ctypes.create_string_buffer(needed.value)
                    status = self.information(handle, 60, buffer, len(buffer), ctypes.byref(needed))
                    if status < 0:
                        raise OSError("Cannot inspect installed process identity.")
                    value = UnicodeString.from_buffer(buffer)
                    address = value.Buffer or 0
                    if value.Length % 2 or not ctypes.addressof(buffer) <= address <= ctypes.addressof(buffer) + len(buffer) - value.Length:
                        raise RuntimeError("Invalid process command-line buffer.")
                    command = ctypes.wstring_at(address, value.Length // 2)
                    count = ctypes.c_int()
                    argv_address = self.argument_pointer(command, ctypes.byref(count))
                    if not argv_address:
                        raise ctypes.WinError(ctypes.get_last_error())
                    try:
                        argv = (ctypes.c_wchar_p * count.value).from_address(argv_address)
                        arguments = tuple(argument(value) for value in argv)
                    finally:
                        self.free(argv_address)
                    editor = (
                        PureWindowsPath(USER / "Projects" / "workspace" / ".venv" / "Scripts" / "python.exe"),
                        PureWindowsPath(USER / ".vscode" / "extensions"),
                    )
                    role = role_for(arguments, windowed=PureWindowsPath(image.value).name.casefold() == "pythonw.exe", editor=editor)
                    if role is not None:
                        times = [wintypes.FILETIME() for _ in range(4)]
                        if not self.process_times(handle, *(ctypes.byref(value) for value in times)):
                            raise ctypes.WinError(ctypes.get_last_error())
                        counters = [(value.dwHighDateTime << 32) | value.dwLowDateTime for value in times]
                        return Observation(
                            Process(
                                pid,
                                entry.th32ParentProcessID,
                                role,
                                image.value,
                                unix_ms(times[0]),
                                user_cpu_100ns=counters[3],
                                kernel_cpu_100ns=counters[2],
                            ),
                            arguments,
                        )
            finally:
                self.close(handle)
        return None
