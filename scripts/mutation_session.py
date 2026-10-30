"""Run one mutation's pytest session with the edit check's runtime and fixtures.

scripts/mutate.py starts this inside each disposable source copy, so a campaign
can select any test that `Dev.cmd check` runs, including SDK and pywin32 tests.
"""

import sys
from collections.abc import Generator
from pathlib import Path

import pytest

from scripts.check import NATIVE_SOURCE_RUNTIME, scratch_directory


class CheckFixtures:
    """Replace pytest's tmp_path with the edit check's shallow scratch folder."""

    @pytest.fixture
    def tmp_path(self) -> Generator[Path]:
        with scratch_directory() as scratch:
            yield scratch


def main() -> None:
    # Activate and attach the test desktop before pytest captures the streams
    # the isolated relaunch inherits.
    NATIVE_SOURCE_RUNTIME.activate()
    raise SystemExit(pytest.main(sys.argv[1:], plugins=[CheckFixtures()]))


if __name__ == "__main__":
    main()
