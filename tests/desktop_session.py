"""Launch tests on an unshown desktop using the already installed win32more API.

The launcher owns the desktop until its isolated process tree exits. Specifying
a startup desktop contains native children too; moving only a thread does not.
Never switch the input desktop. Launch failures block tests instead of exposing
their windows on the user's desktop.
"""

import ctypes
import os
import subprocess
import sys
import time
import uuid
from collections.abc import Generator
from contextlib import contextmanager

from win32more import WinError
from win32more.Windows.Win32.Foundation import CloseHandle, DuplicateHandle, GetLastError
from win32more.Windows.Win32.System.Console import GetStdHandle
from win32more.Windows.Win32.System.StationsAndDesktops import CloseDesktop, CreateDesktopW, GetThreadDesktop, GetUserObjectInformationW
from win32more.Windows.Win32.System.Threading import (
    PROCESS_INFORMATION,
    STARTUPINFOW,
    CreateProcessW,
    GetCurrentProcess,
    GetCurrentThreadId,
    ResumeThread,
)

from winapi.processes import Process, ProcessJob


def current_name() -> str:
    handle = GetThreadDesktop(GetCurrentThreadId())
    if handle is None:
        raise WinError(GetLastError())
    buffer = ctypes.create_unicode_buffer(256)
    if not GetUserObjectInformationW(handle, 2, ctypes.addressof(buffer), ctypes.sizeof(buffer), None):
        raise WinError(GetLastError())
    return buffer.value


@contextmanager
def inherited_stream(identifier: int) -> Generator[int | None]:
    source = GetStdHandle(identifier)
    if source is None or source == ctypes.c_void_p(-1).value:
        yield None
        return
    # Only these temporary duplicates are inheritable. Preserve the caller's
    # handles and flags, and release our duplicates after child creation.
    duplicate = ctypes.c_void_p()
    owner = GetCurrentProcess()
    if not DuplicateHandle(owner, source, owner, duplicate, 0, 1, 2):
        raise WinError(GetLastError())
    handle = duplicate.value
    if handle is None:
        raise OSError("Windows did not duplicate a test stream")
    try:
        yield handle
    finally:
        CloseHandle(handle)


def run_isolated(name: str) -> int:
    # STARTUPINFO and PROCESS_INFORMATION are mutable native buffers owned only
    # by this launch. Preserve interpreter arguments, cwd, environment, streams
    # and exit status; the job owns cleanup if the launcher is interrupted.
    command = ctypes.create_unicode_buffer(subprocess.list2cmdline((sys.executable, *sys.orig_argv[1:])))
    info = PROCESS_INFORMATION()
    job = ProcessJob()
    try:
        with inherited_stream(-10) as stdin, inherited_stream(-11) as stdout, inherited_stream(-12) as stderr:
            startup = STARTUPINFOW(cb=ctypes.sizeof(STARTUPINFOW), lpDesktop=name, dwFlags=0x100,
                                  hStdInput=stdin, hStdOutput=stdout, hStdError=stderr)
            if not CreateProcessW(sys.executable, command, None, None, 1, 0x08000004, None, None, startup, info):
                raise WinError(GetLastError())
        process = Process(info.hProcess, info.dwProcessId)
        try:
            job.add(process.pid)
            if ResumeThread(info.hThread) == 0xFFFFFFFF:
                raise WinError(GetLastError())
            while (code := process.poll()) is None:
                time.sleep(.05)
            return code
        finally:
            CloseHandle(info.hThread)
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
    finally:
        job.close()


def attach() -> None:
    # Relaunch once; Python and native children inherit the isolated process's
    # startup desktop. Only this bootstrap owns the environment write.
    name = os.environ.get("WORKSPACE_TEST_DESKTOP")
    if name is None:
        name = "workspace-tests-" + uuid.uuid4().hex
    if not name.startswith("workspace-tests-") or not name.removeprefix("workspace-tests-").isalnum():
        raise ValueError("Invalid Workspace test desktop identity")
    if current_name() == name:
        return
    # Read/write/create/enumerate windows and desktop objects. Never request
    # DESKTOP_SWITCHDESKTOP or call SwitchDesktop.
    handle = CreateDesktopW(name, None, None, 0, 0x00CF, None)
    if not handle:
        raise WinError(GetLastError())
    try:
        os.environ["WORKSPACE_TEST_DESKTOP"] = name
        sys.stdout.flush()
        sys.stderr.flush()
        code = run_isolated(name)
    finally:
        CloseDesktop(handle)
    # This is a process handoff, not a collection exception. Pytest intercepts
    # SystemExit during package import and would report an internal error even
    # after a successful isolated run. Release our owners above, then preserve
    # the child's status without returning to the launcher's test collection.
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)
