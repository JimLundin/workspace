"""Enum translations name every member, or their module refuses to import."""

from enum import Enum, auto

from contracts.members import every_member


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
