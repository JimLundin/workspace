"""Retained native surfaces must never carry another bubble's input or timing."""

import sys
import unittest

if sys.platform != "win32":
    raise unittest.SkipTest("Windows bubble resource ownership")

lazy import shiboken6
lazy from PySide6 import QtCore

from assistant.agent_session import ChatMessage
from assistant.notifications import Entry, Toast
from assistant.qt_runtime import prepare
from assistant.toast_card import Card, CardOwner, Finish, Measure
from assistant.toast_stack import Frame
from tests.test_windows_agent_toasts import notifications
from winapi import windows

prepare()


def test_settled_bubbles_stop_their_native_frame_publication_loop() -> None:
    # Defect: a separate glass frame loop keeps querying native geometry at
    # 60 Hz after all bubble motion, reveals and scrolling have stopped.
    with notifications(animated=True) as panel:
        panel.agent.say("A short fictional reply.")
        panel.pump()
        panel.settle()
        assert not panel.view.animation_timer.isActive()
        assert not panel.view.loop.timer.isActive(), "Idle bubbles kept native frame work running."


def test_repeated_observations_preserve_the_cards_animation_deadline() -> None:
    # Defect: incoming observations restart the card timer before it can fire,
    # starving movement, text reveals, scrolling and the working spinner.
    with notifications(animated=True) as panel:
        panel.agent.begin("Review the fictional figures")
        panel.pump()
        frames = 0

        def painted() -> None:
            nonlocal frames
            frames += 1

        updates = QtCore.QTimer(panel.root)
        updates.setInterval(5)
        updates.timeout.connect(panel.view.refresh)
        waiting = QtCore.QEventLoop()
        try:
            panel.view.animation_timer.timeout.connect(painted)
            updates.start()
            QtCore.QTimer.singleShot(150, waiting.quit)
            waiting.exec()
            assert frames >= 3, "Incoming observations starved card animation."
        finally:
            updates.stop()
            updates.deleteLater()


def test_measuring_another_bubble_preserves_each_bubbles_prepared_document() -> None:
    # Defect: a shared scratch document discards another card's text layout,
    # forcing full reconstruction instead of updating its changed tail.
    with notifications() as panel:
        panel.agent.say("First fictional reply with its own measured text.")
        panel.agent.say("Second fictional reply with different measured text.")
        panel.pump()
        assert len(panel.view.cards) == 2
        for card in panel.view.cards.values():
            assert card.prepared is not None
            assert card.measurement.body.spans == card.prepared[2].spans, "Another bubble overwrote its prepared document."


def test_fractional_scaling_keeps_measurement_and_viewport_on_one_text_width() -> None:
    # Defect: the physical-pixel budget becomes a fractional logical width,
    # repeatedly reflowing the full reply between measurement and viewport fit.
    with notifications():
        measurement = Measure()
        measurement.scale = 1.25
        try:
            content = Entry(0, ChatMessage("Workspace", "A long fictional paragraph.\n\n" * 80, 100))
            prepared = measurement.prepare(content, 400)
            measured_width = measurement.body.qt.textWidth()
            fitted = measurement.layout(prepared, prepared.width, 300)
            assert fitted.body_height < prepared.body_height
            assert measurement.body.qt.textWidth() == measured_width, "Fitting changed the measured text width."
        finally:
            measurement.close()


def test_expired_bubble_reuses_its_windows_without_retaining_content() -> None:
    # Defects: rebuilding retired windows, or showing old content in a reused card.
    with notifications() as panel:
        panel.view.resume()
        panel.agent.say("First fictional reply.")
        panel.pump()
        card = next(iter(panel.view.cards.values()))
        handle = card.handle
        layer = card.layer
        assert layer is not None
        panel.advance(31)
        assert not panel.view.cards
        assert windows.exists(handle) and windows.exists(layer.handle)
        assert not windows.is_visible(handle) and not windows.is_visible(layer.handle)
        panel.agent.say("Second fictional reply.")
        panel.pump()
        reused = next(iter(panel.view.cards.values()))
        assert reused is card and reused.handle == handle and reused.layer is layer
        assert "Second fictional reply." in reused.text.toPlainText()
        assert "First fictional reply." not in reused.text.toPlainText()
        panel.agent.close()
        panel.pump()
        assert not windows.exists(handle) and not windows.exists(layer.handle)
        assert not shiboken6.isValid(card.window)


def test_animation_clock_starts_after_native_preparation() -> None:
    # Defect: synchronous preparation consumes the transition before its first tick.
    class SlowCard(Card):
        __slots__ = ()

        def apply_style(self, finish: Finish) -> None:
            super().apply_style(finish)
            panel.now += 0.4

    with notifications(animated=True, create_card=SlowCard) as panel:
        panel.agent.say("Fictional reply with a slow native preparation.")
        panel.pump()
        card = next(iter(panel.view.cards.values()))
        assert card.motion is not None, "Preparation used up the animation's entire duration."
        assert card.motion.at == panel.now and card.alpha == 0
        panel.now += 0.14
        panel.view.tick()
        assert 0 < card.alpha < 1


def test_translation_does_not_relayout_unchanged_bubble_contents() -> None:
    # Defect: every translation frame reshapes text and lays out child controls.
    class CountedCard(Card):
        __slots__ = ("layouts",)

        def __init__(self, owner: CardOwner, toast: Toast, width: int) -> None:
            self.layouts = 0
            super().__init__(owner, toast, width)

        def place_content(self, width: float, height: float, details: float) -> None:
            self.layouts += 1
            super().place_content(width, height, details)

    with notifications(create_card=CountedCard) as panel:
        panel.agent.say("Fictional reply.")
        panel.pump()
        card = next(iter(panel.view.cards.values()))
        assert isinstance(card, CountedCard)
        frame = card.frame
        layouts = card.layouts
        card.position(card.right, Frame(frame.y - 10, frame.width, frame.height, frame.alpha, frame.details))
        assert card.y == frame.y - 10
        assert card.layouts == layouts, "Translation relaid out content."
