"""Which tests a change selects, how the check runs them, and which import failures only mean "not Windows".

A changed Python file selects the test modules that import it, directly or
through test helpers. A changed asset in ASSET_READERS counts as a change to its
readers; any other non-Python change selects every test.
"""

import ast
import importlib
import os
import sys
import traceback
from collections.abc import Iterable, Iterator, Mapping
from pathlib import Path
from typing import Final

from scripts.source_analysis import imports, module_name

_WINDOWS_ONLY = ("WinDLL", "WINFUNCTYPE", "windll", "winreg", "msvcrt", "_winapi", "PySide6", "shiboken6", "win32more")
"""Signs that an import failed only because this isn't Windows."""


_ON_WINDOWS: bool = sys.platform == "win32"


_DOCUMENTS = ("docs/", ".github/", ".vscode/", "typings/", ".git")
"""Changes no test reads: documentation, repository and editor configuration, type stubs."""


_TEXT = frozenset({"AGENTS.md", "README.md", "GLOSSARY.md"})


ASSET_READERS: Final = frozendict(
    {
        "pyproject.toml": ("scripts/architecture.py", "scripts/quality.py", "scripts/source_analysis.py", "scripts/check.py"),
        "Dev.cmd": ("scripts/check.py", "launch.py"),
        "scripts/dev.ps1": ("scripts/check.py", "launch.py"),
        "StartWorkspace.cmd": ("launch.py",),
        "assistant/uia.ps1": ("assistant/uia.py",),
        "desktop_ui/fonts/": ("desktop_ui/components/typeface.py", "desktop_ui/components/text.py"),
        "tests/uia_fixture.ps1": ("tests/test_windows_computer.py",),
        # A sample log for `scripts.navigation_report --log`; no test reads it.
        "tests/navigation_report_fixture.jsonl": (),
    }
)
"""Each non-Python source file (or folder ending in /) and the source files that read it.

A changed asset counts as a change to its readers. Any other non-Python file, such as
a runtime pin, has unknown readers and selects every test.
"""


def asset_readers(name: str) -> tuple[str, ...] | None:
    """The source files a changed non-Python file affects: none for documents, None when unknown."""
    if name.startswith(_DOCUMENTS) or name in _TEXT:
        return ()
    # A page script `<module>.<script>.js` is read by the module beside it.
    match name.removesuffix(".js").partition("."):
        case (module, ".", script) if name.endswith(".js") and script:
            return (module + ".py",)
        case _:
            pass
    for asset, readers in ASSET_READERS.items():
        if name == asset or (asset.endswith("/") and name.startswith(asset)):
            return readers
    return None


type Imports = Mapping[str, frozenset[str]]
"""Each test source file (tests/x.py) and the modules it imports, with their packages."""


def tests_imports(root: Path) -> dict[str, frozenset[str]]:
    """The imports of every test source file directly under tests/."""
    return {
        path.relative_to(root).as_posix(): imports(path.relative_to(root).as_posix(), ast.parse(path.read_text(encoding="utf-8")))
        for path in (root / "tests").glob("*.py")
    }


def module_inputs(found: Imports) -> dict[str, frozenset[str]]:
    """Each test module's inputs: itself, the test helpers it reaches, and the modules those import.

    Production imports are not followed further; the full suite runs in CI.
    """
    by_module = {module_name(name): (name, modules) for name, modules in found.items()}
    helpers = frozenset(module for module, (name, _) in by_module.items() if not Path(name).name.startswith("test_"))
    return {
        name: _reached(frozenset({module, *modules}), by_module, helpers)
        for module, (name, modules) in sorted(by_module.items())
        if module not in helpers
    }


def _reached(inputs: frozenset[str], by_module: Mapping[str, tuple[str, frozenset[str]]], helpers: frozenset[str]) -> frozenset[str]:
    """`inputs` with everything the test helpers among them import, transitively."""
    extra = frozenset(name for helper in inputs & helpers for name in _helper_imports(by_module[helper])) - inputs
    return _reached(inputs | extra, by_module, helpers) if extra else inputs


def _helper_imports(entry: tuple[str, frozenset[str]]) -> frozenset[str]:
    _, modules = entry
    return modules


def affected_tests(root: Path, changed: Iterable[str], found: Imports | None = None) -> frozenset[str] | None:
    """Test modules whose inputs include a changed module, or a reader of a changed asset.

    Dev.cmd check passes its cached `found`. None means every test: a changed
    non-Python file has unknown readers.
    """
    groups = tuple(_readers(name) for name in changed)
    if any(group is None for group in groups):
        return None
    reached = frozenset(module_name(reader) for group in groups if group is not None for reader in group)
    if not reached:
        return frozenset()
    return frozenset(name for name, inputs in module_inputs(tests_imports(root) if found is None else found).items() if inputs & reached)


def _readers(name: str) -> tuple[str, ...] | None:
    """The source files a change to `name` counts as: itself if it is Python, else its readers."""
    return (name,) if name.endswith((".py", ".pyw")) else asset_readers(name)


# Reviewed effect owners: fake desktop adapters, private localhost endpoints,
# and per-function temporary stores. These modules never use the shared desktop
# or installed source, so they run in worker processes alongside the remaining
# portable modules. An explicit inventory, rather than filename inference, keeps
# new/native tests sequential until their effects have been reviewed.
# Heavier modules lead the queue.
PORTABLE = (
    "tests/test_agent.py",
    "tests/test_architecture.py",
    "tests/test_quality.py",
    "tests/test_work_store.py",
    "tests/test_work_actions.py",
    "tests/test_meetings.py",
    "tests/test_selfcheck.py",
    "tests/test_computer_tools.py",
    "tests/test_work_execution.py",
    "tests/test_feed_triage_service.py",
    "tests/test_commands.py",
    "tests/test_project_context.py",
    "tests/test_llm.py",
    "tests/test_background_agent.py",
    "tests/test_source_analysis.py",
    "tests/test_work_agent.py",
    "tests/test_features.py",
    "tests/test_work_submissions.py",
)


# Strict elapsed deadlines suffer under competing SDK/source work. These and all
# native modules run after the workers exit, keeping their fixture costs stable.
AFTER_WORKERS = frozenset({"tests/test_agent_streaming.py"})


NATIVE_LANES: Final = (
    # Each launches real Edge processes on disposable profiles.
    ("tests/test_windows_browser.py",),
    ("tests/test_windows_test_desktop.py",),
    ("tests/test_windows_computer.py", "tests/test_windows_development.py"),
)
"""Slow native modules that wait on child processes and share no machine-wide state.

Each lane, and then the remaining native modules together, runs in its own process
on its own private desktop once the portable workers exit. Audio endpoints and the
keyboard hook stay in the remaining lane, so their modules never overlap. """


def windows_only(error: BaseException) -> bool:
    return not _ON_WINDOWS and isinstance(error, (ImportError, AttributeError, OSError)) and any(w in str(error) for w in _WINDOWS_ONLY)


def _sources(root: Path) -> Iterator[Path]:
    # Do not enumerate bundled interpreters and dependencies just to discard them.
    for folder, directories, files in os.walk(root):
        directories[:] = sorted(name for name in directories if not name.startswith((".", "__pycache__")))
        for name in sorted(files):
            path = Path(folder) / name
            if path.suffix in (".py", ".pyw") and not name.startswith((".", "__pycache__")):
                yield path


def _modules(root: Path) -> Iterator[str]:
    """Top-level modules, and every module of every top-level package (tests excepted)."""
    for path in _sources(root):
        relative = path.relative_to(root).with_suffix("")
        parts = relative.parts
        if parts[0] == "tests" or path.suffix == ".pyw":
            continue
        if len(parts) == 1 or (root / parts[0] / "__init__.py").exists():
            yield ".".join(p for p in parts if p != "__init__") if parts[-1] == "__init__" else ".".join(parts)


def import_all(root: Path) -> Iterator[str]:
    """Import every production module, yielding a report of each that fails."""
    for name in _modules(root):
        try:
            importlib.import_module(name)
        except Exception as error:
            if not windows_only(error):
                yield f"doesn't import: {name}\n{''.join(traceback.format_exception(error))}"
