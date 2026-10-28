"""Prepare Python's deferred executor export before native Qt bindings load."""

import concurrent.futures


def prepare() -> None:
    """PySide6 6.12 must see a resolved executor for the SDK's asyncio.to_thread.

    Qt consumers declare lazy imports from PySide6 and call this before their
    first native binding access. This module owns ordering, not Qt exports.
    """
    _executor = concurrent.futures.ThreadPoolExecutor
