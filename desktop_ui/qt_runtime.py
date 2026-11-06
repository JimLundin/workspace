"""Prepare Python's deferred exports before native Qt bindings load."""

import concurrent.futures

import pydantic


def prepare() -> None:
    """Resolve deferred exports that PySide6 6.12's import hook would otherwise re-enter.

    PySide6 must see a resolved executor for the SDK's asyncio.to_thread. Its hook
    also inspects each module imported after it; inspecting pydantic's lazily
    exported names mid-import re-enters pydantic and fails as a circular import,
    so the names Workspace validates with are resolved here first.

    Qt consumers declare lazy imports from PySide6 and call this before their
    first native binding access. This module owns ordering, not Qt exports.
    """
    _executor = concurrent.futures.ThreadPoolExecutor
    _validation = (pydantic.BeforeValidator, pydantic.ConfigDict, pydantic.Field, pydantic.TypeAdapter, pydantic.ValidationError)
