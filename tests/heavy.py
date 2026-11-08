"""Opt-in for the native tests that take over the machine: real Edge, nested checks, PowerShell, whole processes.

They are skipped unless `WORKSPACE_HEAVY=1`, so `Dev.cmd check --native` stays
light. Run them when changing what they alone exercise:

    $env:WORKSPACE_HEAVY = "1"; ./Dev.cmd check --native --tests tests/test_windows_browser.py
"""

import os
import unittest


def heavy(why: str) -> None:
    """Skip the calling test unless heavy tests were asked for."""
    if os.environ.get("WORKSPACE_HEAVY") != "1":
        raise unittest.SkipTest(f"heavy ({why}); set WORKSPACE_HEAVY=1 to run it")
