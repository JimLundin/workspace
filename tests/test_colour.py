"""Colours are checked as they're built, so a bad channel never reaches a painter."""

from contracts.status import State
from desktop_ui.colour import Rgb
from desktop_ui.icons import COLOURS


def refused(build: object) -> str:
    try:
        if callable(build):
            build()
    except ValueError as error:
        return str(error)
    raise AssertionError("The colour was accepted.")


def test_a_channel_outside_eight_bits_is_refused() -> None:
    # Defect: a channel of 256 or -1 wraps or clips silently and the tray or bar
    # paints a different colour than the one written; a bool slips in as 0 or 1.
    assert "red channel" in refused(lambda: Rgb(256, 0, 0))
    assert "blue channel" in refused(lambda: Rgb(0, 0, -1))
    assert "green channel" in refused(lambda: Rgb(0, True, 0))


def test_a_written_colour_reads_back_exactly_and_a_malformed_one_is_refused() -> None:
    # Defect: a token colour like "#2ea078" parses to other channels, or "#2ea07"
    # or "2ea078" is accepted and paints garbage.
    assert Rgb.parse("#2ea078") == Rgb(46, 160, 120) and Rgb(46, 160, 120).hex == "#2ea078"
    for text in ("#2ea07", "2ea078", "#2ea07g", "#2ea0780"):
        assert "#rrggbb" in refused(lambda text=text: Rgb.parse(text))


def test_every_tray_state_has_its_own_colour() -> None:
    # Defect: two states share one colour, so the dot can't tell them apart.
    assert len(set(COLOURS.values())) == len(State)
