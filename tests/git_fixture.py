"""Temporary Git repositories that never inherit another repository's location.

A parent can carry variables that relocate a child's repository, work tree,
index, objects or configuration: a test runner or coordinator might set them for
one repository. An inherited value overrides `git -C folder` and the child's
working directory, so `git init` and `git commit` meant for a temporary
repository write into the other one. Every test's Git child removes them.
"""

import os
import subprocess
from collections.abc import Mapping
from pathlib import Path

# `git rev-parse --local-env-vars` (Git 2.25), plus GIT_CONFIG_COUNT, which carries
# `-c` configuration into children since Git 2.31.
LOCATING = frozenset(
    {
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_COMMON_DIR",
        "GIT_CONFIG",
        "GIT_CONFIG_COUNT",
        "GIT_CONFIG_PARAMETERS",
        "GIT_DIR",
        "GIT_GRAFT_FILE",
        "GIT_IMPLICIT_WORK_TREE",
        "GIT_INDEX_FILE",
        "GIT_INTERNAL_SUPER_PREFIX",
        "GIT_NO_REPLACE_OBJECTS",
        "GIT_OBJECT_DIRECTORY",
        "GIT_PREFIX",
        "GIT_REPLACE_REF_BASE",
        "GIT_SHALLOW_FILE",
        "GIT_WORK_TREE",
    }
)


def isolated(environ: Mapping[str, str]) -> frozendict[str, str]:
    """`environ` without repository-locating variables; Windows names compare case-insensitively."""
    return frozendict((name, value) for name, value in environ.items() if name.upper() not in LOCATING)


def initialized(folder: Path) -> None:
    """An empty repository at `folder`, whatever GIT_DIR or GIT_WORK_TREE this process carries."""
    subprocess.run(("git", "init", "--quiet", str(folder)), check=True, capture_output=True, env=isolated(os.environ))
