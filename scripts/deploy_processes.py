"""Native process inventory: no PowerShell process per shutdown/readiness poll.

Command lines are classified inside this boundary and never included in receipts.
Process handles bind executable, creation time and exit status across PID reuse.
"""

import ctypes
import os
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

from scripts.deploy_values import Identity, Role
from scripts.development_paths import USER


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
        return {'pid': self.pid, 'parent_pid': self.parent_pid, 'role': self.role,
                'executable': self.executable, 'created_ms': self.created_ms}


def role_for(arguments: tuple[str, ...], *, windowed: bool,
             editor: tuple[PureWindowsPath, PureWindowsPath] | None = None) -> Role | None:
    arguments = (arguments[0], *(value for value in arguments[1:] if value not in ('-B', '-u', '-s'))) if arguments else ()
    if editor is not None and len(arguments) == 2 and PureWindowsPath(arguments[0]) == editor[0]:
        script = PureWindowsPath(arguments[1])
        if script.is_relative_to(editor[1]):
            relative = script.relative_to(editor[1]).parts
            if (len(relative) == 4 and relative[0].casefold().startswith('ms-python.black-formatter-')
                    and tuple(part.casefold() for part in relative[1:]) == ('bundled', 'tool', 'lsp_server.py')):
                return None
    if len(arguments) >= 3 and arguments[1:3] == ('-m', 'assistant.browser_host'):
        return None
    if windowed:
        if len(arguments) == 3 and arguments[1] == '-m' and arguments[2] in ('assistant', 'automation', 'miryoku'):
            match arguments[2]:
                case 'assistant':
                    return 'assistant'
                case 'automation':
                    return 'automation'
                case 'miryoku':
                    return 'miryoku'
        if len(arguments) == 2 and Path(arguments[1]).name.casefold() in ('workspace.pyw', 'keeper.py'):
            return 'keeper'
    return 'runtime'


class Entry(ctypes.Structure):
    _fields_ = [('dwSize', wintypes.DWORD), ('cntUsage', wintypes.DWORD), ('th32ProcessID', wintypes.DWORD),
                ('th32DefaultHeapID', ctypes.c_size_t), ('th32ModuleID', wintypes.DWORD), ('cntThreads', wintypes.DWORD),
                ('th32ParentProcessID', wintypes.DWORD), ('pcPriClassBase', wintypes.LONG), ('dwFlags', wintypes.DWORD),
                ('szExeFile', wintypes.WCHAR * 260)]


class UnicodeString(ctypes.Structure):
    _fields_ = [('Length', wintypes.USHORT), ('MaximumLength', wintypes.USHORT), ('Buffer', ctypes.c_void_p)]


def inventory(live: Path) -> tuple[Process, ...]:  # noqa: PLR0915 -- one handle-owned native enumeration
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    nt = ctypes.WinDLL('ntdll')
    shell = ctypes.WinDLL('shell32', use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.Process32FirstW.argtypes = kernel.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
    kernel.Process32FirstW.restype = kernel.Process32NextW.restype = wintypes.BOOL
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    kernel.GetProcessTimes.restype = wintypes.BOOL
    nt.NtQueryInformationProcess.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.ULONG, ctypes.POINTER(wintypes.ULONG)]
    nt.NtQueryInformationProcess.restype = wintypes.LONG
    shell.CommandLineToArgvW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
    shell.CommandLineToArgvW.restype = ctypes.POINTER(wintypes.LPWSTR)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    snapshot = kernel.CreateToolhelp32Snapshot(2, 0)
    if snapshot == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    rows: list[Process] = []
    prefix = str(live).casefold() + '\\'
    try:
        entry = Entry()
        entry.dwSize = ctypes.sizeof(entry)
        more = kernel.Process32FirstW(snapshot, ctypes.byref(entry))
        while more:
            pid = entry.th32ProcessID
            handle = kernel.OpenProcess(0x1000, False, pid) if pid and pid != os.getpid() else None
            if handle:
                try:
                    image = ctypes.create_unicode_buffer(32768)
                    size = wintypes.DWORD(len(image))
                    if kernel.QueryFullProcessImageNameW(handle, 0, image, ctypes.byref(size)) and image.value.casefold().startswith(prefix):
                        needed = wintypes.ULONG()
                        nt.NtQueryInformationProcess(handle, 60, None, 0, ctypes.byref(needed))
                        if not ctypes.sizeof(UnicodeString) <= needed.value <= 1_000_000:
                            raise RuntimeError('Cannot inspect an installed process command line.')
                        buffer = ctypes.create_string_buffer(needed.value)
                        status = nt.NtQueryInformationProcess(handle, 60, buffer, len(buffer), ctypes.byref(needed))
                        if status < 0:
                            raise OSError('Cannot inspect installed process identity.')
                        value = UnicodeString.from_buffer(buffer)
                        address = value.Buffer or 0
                        if value.Length % 2 or not ctypes.addressof(buffer) <= address <= ctypes.addressof(buffer) + len(buffer) - value.Length:
                            raise RuntimeError('Invalid process command-line buffer.')
                        command = ctypes.wstring_at(address, value.Length // 2)
                        count = ctypes.c_int()
                        argv = shell.CommandLineToArgvW(command, ctypes.byref(count))
                        if not argv:
                            raise ctypes.WinError(ctypes.get_last_error())
                        try:
                            arguments = tuple(argv[index] for index in range(count.value))
                        finally:
                            kernel.LocalFree(argv)
                        editor = (PureWindowsPath(USER / 'Projects' / 'workspace' / '.venv' / 'Scripts' / 'python.exe'),
                                  PureWindowsPath(USER / '.vscode' / 'extensions'))
                        role = role_for(arguments, windowed=Path(image.value) == live / '.python' / 'pythonw.exe', editor=editor)
                        if role is not None:
                            times = [wintypes.FILETIME() for _ in range(4)]
                            if not kernel.GetProcessTimes(handle, *(ctypes.byref(value) for value in times)):
                                raise ctypes.WinError(ctypes.get_last_error())
                            counters = [(value.dwHighDateTime << 32) | value.dwLowDateTime for value in times]
                            rows.append(Process(pid, entry.th32ParentProcessID, role, image.value,
                                                counters[0] // 10000 - 11644473600000,
                                                user_cpu_100ns=counters[3], kernel_cpu_100ns=counters[2]))
                finally:
                    kernel.CloseHandle(handle)
            more = kernel.Process32NextW(snapshot, ctypes.byref(entry))
        if ctypes.get_last_error() != 18:
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        kernel.CloseHandle(snapshot)
    return tuple(sorted(rows, key=lambda row: row.pid))
