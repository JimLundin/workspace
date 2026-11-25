from desktop_ui.colour import Rgb


def refused(build: object) -> str:
    try:
        if callable(build):
            build()
    except ValueError as error:
        return str(error)
    raise AssertionError("The colour was accepted.")


def test_a_channel_outside_eight_bits_is_refused() -> None:
    assert "red channel" in refused(lambda: Rgb(256, 0, 0))
    assert "blue channel" in refused(lambda: Rgb(0, 0, -1))
    assert "green channel" in refused(lambda: Rgb(0, True, 0))


def test_a_written_colour_reads_back_exactly_and_a_malformed_one_is_refused() -> (
    None
):
    assert (
        Rgb.parse("#2ea078") == Rgb(46, 160, 120)
        and Rgb(46, 160, 120).hex == "#2ea078"
    )
    for text in ("#2ea07", "2ea078", "#2ea07g", "#2ea0780"):
        assert "#rrggbb" in refused(lambda text=text: Rgb.parse(text))
