"""Retained native surfaces must never carry another bubble's input or timing."""

import sys
import unittest

if sys.platform != "win32":
    raise unittest.SkipTest("Windows bubble resource ownership")

lazy import shiboken6

from assistant.agent_toasts import AgentToasts
from assistant.notifications import Content, Frame, Toast
from assistant.qt_runtime import prepare
from assistant.toast_card import Card
from tests.test_windows_agent_toasts import notifications
from winapi import appearance, windows

prepare()


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

        def apply_style(self, content: Content, preference: appearance.Preference) -> None:
            super().apply_style(content, preference)
            panel.now += 0.4

    with notifications(animated=True, create_card=SlowCard) as panel:
        panel.agent.say("Fictional reply with a slow native preparation.")
        panel.pump()
        card = next(iter(panel.view.cards.values()))
        assert card.motion is not None, "Preparation used up the animation's entire duration."
        assert card.motion.started == panel.now and card.alpha == 0
        panel.now += 0.14
        panel.view.tick()
        assert 0 < card.alpha < 1


def test_translation_does_not_relayout_unchanged_bubble_contents() -> None:
    # Defect: every translation frame reshapes text and lays out child controls.
    class CountedCard(Card):
        __slots__ = ("layouts",)

        def __init__(self, owner: AgentToasts, toast: Toast, width: int) -> None:
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
