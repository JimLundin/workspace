"""Temporary Git repositories that never inherit another repository's location."""

import os
import subprocess
from pathlib import Path

from scripts.git_environment import isolated


def initialized(folder: Path) -> None:
    """An empty repository at `folder`, whatever GIT_DIR or GIT_WORK_TREE this process carries."""
    subprocess.run(("git", "init", "--quiet", str(folder)), check=True, capture_output=True, env=isolated(os.environ))
