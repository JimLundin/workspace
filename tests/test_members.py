"""Enum and Literal translations name every value, or their module refuses to import."""

from enum import Enum, auto
from typing import Literal

from contracts.members import every_literal, every_member

type Signal = Literal["walk", "wait", "run"]


class Light(Enum):
    RED = auto()
    AMBER = auto()
    GREEN = auto()


def test_a_translation_missing_a_member_is_refused_by_name() -> None:
    # Defect: a member added to an enum has no value in a translation table, so
    # the first lookup for it raises KeyError deep in a paint or a reply instead
    # of when the module loads.
    try:
        every_member(Light, {Light.RED: "stop"})
    except ValueError as error:
        assert str(error) == "Light has no value for: AMBER, GREEN"
    else:
        raise AssertionError("A partial translation was accepted.")
    assert every_member(Light, {Light.RED: 1, Light.AMBER: 2, Light.GREEN: 3})[Light.AMBER] == 2


def test_a_literal_translation_missing_a_value_is_refused_by_name() -> None:
    # Defect: a value added to a Literal alias has no entry in its table, so the
    # first lookup raises KeyError mid-render instead of when the module loads.
    try:
        every_literal(Signal, {"walk": "Walk now"})
    except ValueError as error:
        assert str(error) == "Signal has no value for: 'wait', 'run'"
    else:
        raise AssertionError("A partial translation was accepted.")
    assert every_literal(Signal, {"walk": 1, "wait": 2, "run": 3})["run"] == 3
