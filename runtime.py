"""Activate Workspace's matching dependencies in the running Python 3.15 interpreter."""

import json
import os
import site
import struct
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Interpreter:
    platform: str
    version: tuple[int, int]
    pointer_bytes: int


def bundled(root: Path | None = None) -> Path | None:
    """Source copies reuse the installed bundle; an adjacent bundle takes precedence."""
    folder = (root if root is not None else Path(__file__).resolve().parent) / ".runtime"
    if folder.is_dir():
        return folder
    inherited = os.environ.get("WORKSPACE_BUNDLED_RUNTIME")
    return Path(inherited) if inherited and Path(inherited).is_dir() else None


def validate_dependencies(metadata: object, interpreter: Interpreter) -> None:
    # This boundary must validate the manifest before activating dependencies;
    # standard-library parsing and structural validation are required here.
    match metadata:
        case {"python": str() as required}:
            parts = required.split(".")
        case _:
            parts = []
            required = ""
    if len(parts) != 2 or not all(part.isdecimal() for part in parts):
        raise RuntimeError("The bundled dependency manifest has no valid Python version. Extract the complete bundle again.")
    if interpreter.platform != "win32" or interpreter.version != (int(parts[0]), int(parts[1])) or interpreter.pointer_bytes != 8:
        raise RuntimeError(f"These dependencies require Windows x64 Python {required}. Run StartWorkspace.cmd or py -{required}.")


def activate(folder: Path | None = None, *, root: Path | None = None) -> None:
    if folder is None:
        folder = bundled(root)
    if folder is not None:
        metadata: object = json.loads((folder / "manifest.json").read_bytes())
        validate_dependencies(metadata, Interpreter(sys.platform, (sys.version_info.major, sys.version_info.minor), struct.calcsize("P")))
        source = sys.path[0]  # Keep selfcheck's candidate tree ahead of dependencies too.
        sys.path.insert(0, str(folder))
        # Wheels such as pywin32 declare their import and DLL directories in
        # .pth files. Activate those hooks from the checked bundle too.
        site.addsitedir(str(folder))
        bundle_paths = [entry for entry in sys.path if Path(entry).is_relative_to(folder)]
        preferred = [source]
        for entry in bundle_paths:
            if entry not in preferred:
                preferred.append(entry)
        sys.path[:] = preferred + [entry for entry in sys.path if entry not in preferred]
        os.environ["WORKSPACE_BUNDLED_RUNTIME"] = str(folder)
        previous = os.environ.get("PYTHONPATH", "").split(os.pathsep)
        os.environ["PYTHONPATH"] = os.pathsep.join([str(folder), *(entry for entry in previous if entry and entry != str(folder))])
