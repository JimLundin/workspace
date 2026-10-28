"""Ordinary native fixtures own a desktop that is never shown to the user."""

import os
import sys

lazy import tests.desktop_session

if sys.platform == "win32" and os.environ.get("WORKSPACE_E2E") != "1":
    tests.desktop_session.attach()
