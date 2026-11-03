"""The mutation session's pytest plugin: the edit check's shallow tmp_path.

pytest is a mutation-campaign tool, not a runtime dependency. selfcheck imports
every production module but no test helper, so the fixture lives here.
"""

from collections.abc import Generator
from pathlib import Path

import pytest

from scripts.check import scratch_directory


class CheckFixtures:
    """Replace pytest's tmp_path with the edit check's shallow scratch folder."""

    @pytest.fixture
    def tmp_path(self) -> Generator[Path]:
        with scratch_directory() as scratch:
            yield scratch
