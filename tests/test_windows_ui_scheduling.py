"""Queued desktop work must yield frames and retain FIFO ownership."""

import sys
import time
import unittest

if sys.platform != "win32":
    raise unittest.SkipTest("Windows Qt scheduling")

lazy from PySide6 import QtWidgets

from assistant.ui import Ui


def test_ui_queue_yields_before_a_batch_consumes_the_frame_budget() -> None:
    # Defect: a count-only queue limit runs dozens of individually short jobs
    # consecutively, blocking every window's animation and input delivery.
    ui = Ui()
    delivered: tuple[int, ...] = ()

    def observe(root: QtWidgets.QApplication) -> None:
        nonlocal delivered
        time.sleep(0.002)  # A concrete short wait, such as a local storage read.
        delivered = (*delivered, len(delivered))

    try:
        for _ in range(24):
            ui.post(observe)
        ui.drain()
        assert 0 < len(delivered) < 24, "A queue batch consumed multiple animation frames."
        while len(delivered) < 24:
            ui.drain()
        assert delivered == tuple(range(24)), "Yielding dropped or repeated queued work."
    finally:
        ui.close()
        ui.run()


def test_nested_event_delivery_cannot_enter_another_queued_job() -> None:
    # Defect: a job pumps native events and a nested queue drain enters the next
    # job before the first finishes publishing its state.
    ui = Ui()
    delivered: tuple[str, ...] = ()

    def first(root: QtWidgets.QApplication) -> None:
        nonlocal delivered
        delivered = (*delivered, "start")
        ui.drain()
        delivered = (*delivered, "finish")

    def second(root: QtWidgets.QApplication) -> None:
        nonlocal delivered
        delivered = (*delivered, "next")

    try:
        ui.post(first)
        ui.post(second)
        ui.drain()
        ui.drain()
        assert delivered == ("start", "finish", "next"), "Native event pumping reentered queued work."
    finally:
        ui.close()
        ui.run()
