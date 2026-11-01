"""How shared glass surfaces read under each material and their owner's observations."""

from assistant.ui_components.appearance import ATTENTION, CanvasBar, Capsule, Card, GlassLook, Menu, Scheme, Shade, SolidLook, look, reading, tokens
from assistant.ui_components.meaning import Tint, Tone
from winapi import appearance


def test_glass_takes_dark_ink_over_a_bright_desktop_and_a_heavier_veil_over_a_mixed_one() -> None:
    # Defects: white ink stays on glass over a bright desktop, or a busy desktop
    # gets the thin veil and small text loses contrast.
    match look(appearance.Material.GLASS, Capsule(appearance.Frost.BRIGHT), Tint.NONE):
        case GlassLook(lettering=lettering):
            assert lettering.ink.color == "#000000"
        case other1:
            raise AssertionError(f"Glass preference produced {other1}")
    match (
        look(appearance.Material.GLASS, Capsule(appearance.Frost.LIGHT), Tint.NONE),
        look(appearance.Material.GLASS, Capsule(appearance.Frost.SMOKED), Tint.NONE),
    ):
        case (GlassLook(veil=thin), GlassLook(veil=heavy)):
            assert heavy.opacity > thin.opacity and heavy.color == thin.color
        case other2:
            raise AssertionError(f"Glass preference produced {other2}")


def test_attention_keeps_its_meaning_under_every_material() -> None:
    # Defects: a waiting question looks like the resting island when transparency
    # is off, or high contrast drops the distinction entirely.
    match look(appearance.Material.GLASS, Capsule(appearance.Frost.BRIGHT), Tint.ATTENTION):
        case GlassLook(veil=veil, lettering=lettering):
            assert veil.color == ATTENTION and lettering.ink.color == "#ffffff"
        case other3:
            raise AssertionError(f"Glass preference produced {other3}")
    match look(appearance.Material.SOLID, Capsule(appearance.Frost.SMOKED), Tint.ATTENTION):
        case SolidLook(fill=fill):
            assert fill == Shade(ATTENTION)
        case other4:
            raise AssertionError(f"Solid preference produced {other4}")
    contrast = appearance.Contrast("#000000", "#ffff00")
    match (look(contrast, Capsule(appearance.Frost.SMOKED), Tint.NONE), look(contrast, Capsule(appearance.Frost.SMOKED), Tint.ATTENTION)):
        case (SolidLook(fill=Shade("#000000"), lettering=resting), SolidLook(fill=Shade("#ffff00"), lettering=asking)):
            assert resting.ink.color == "#ffff00" and asking.ink.color == "#000000"
        case other5:
            raise AssertionError(f"High contrast produced {other5}")


def test_high_contrast_keeps_every_reading_in_the_system_foreground() -> None:
    # Defect: the microphone or a low battery keeps Workspace's colours under high contrast.
    contrast = look(appearance.Contrast("#000000", "#ffff00"), Capsule(appearance.Frost.SMOKED), Tint.NONE).lettering
    assert {reading(contrast, tone, contrast=True) for tone in Tone} == {contrast.ink}
    glass = look(appearance.Material.GLASS, Capsule(appearance.Frost.LIGHT), Tint.NONE).lettering
    assert reading(glass, Tone.LOW, contrast=False) != glass.ink


def test_cards_and_canvas_toolbar_use_system_ink_under_high_contrast() -> None:
    # Defect: routing a large surface through the recipe bypasses high contrast
    # and retains Workspace's veil or translucent text instead of system colours.
    contrast = appearance.Contrast("#000000", "#ffff00")
    for scheme in Scheme:
        for pane in (Card(scheme), CanvasBar(scheme)):
            match look(contrast, pane, Tint.NONE):
                case SolidLook(fill=fill, edge=edge, lettering=ink):
                    assert fill == Shade(contrast.background)
                    assert edge == ink.ink == ink.quiet == Shade(contrast.foreground)
                case other:
                    raise AssertionError(f"High contrast produced {other}")


def test_reduce_transparency_gives_cards_their_scheme_owned_solid_surface() -> None:
    # Defect: a card keeps glass when transparency is disabled, or falls back
    # to the capsule's fixed dark surface instead of its own app scheme.
    for scheme in Scheme:
        theme = tokens(scheme)
        match look(appearance.Material.SOLID, Card(scheme), Tint.NONE):
            case SolidLook(fill=fill, lettering=ink):
                assert fill == Shade(theme.solid) and ink.ink == theme.ink
            case other:
                raise AssertionError(f"Solid preference produced {other}")


def test_expanded_menu_glass_is_thicker_than_its_capsule() -> None:
    # Defect: expansion reuses the capsule's thin veil or changes its colour,
    # reducing the menu's text contrast over the same observed desktop.
    for frost in appearance.Frost:
        match (look(appearance.Material.GLASS, Capsule(frost), Tint.NONE), look(appearance.Material.GLASS, Menu(frost), Tint.NONE)):
            case GlassLook(veil=small), GlassLook(veil=large):
                assert large.opacity > small.opacity and large.color == small.color
            case other:
                raise AssertionError(f"Glass preference produced {other}")
