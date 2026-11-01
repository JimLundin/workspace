"""How capsules read under each Windows material and the desktop beneath them."""

from assistant.island_model import Tint, Tone
from assistant.ui_components.appearance import ATTENTION, GlassLook, Shade, SolidLook, look, reading
from winapi import appearance


def test_glass_takes_dark_ink_over_a_bright_desktop_and_a_heavier_veil_over_a_mixed_one() -> None:
    # Defects: white ink stays on glass over a bright desktop, or a busy desktop
    # gets the thin veil and small text loses contrast.
    match look(appearance.Material.GLASS, appearance.Frost.BRIGHT, Tint.NONE):
        case GlassLook(lettering=lettering):
            assert lettering.ink.color == "#000000"
        case other1:
            raise AssertionError(f"Glass preference produced {other1}")
    match (look(appearance.Material.GLASS, appearance.Frost.LIGHT, Tint.NONE), look(appearance.Material.GLASS, appearance.Frost.SMOKED, Tint.NONE)):
        case (GlassLook(veil=thin), GlassLook(veil=heavy)):
            assert heavy.opacity > thin.opacity and heavy.tint == thin.tint
        case other2:
            raise AssertionError(f"Glass preference produced {other2}")


def test_attention_keeps_its_meaning_under_every_material() -> None:
    # Defects: a waiting question looks like the resting island when transparency
    # is off, or high contrast drops the distinction entirely.
    match look(appearance.Material.GLASS, appearance.Frost.BRIGHT, Tint.ATTENTION):
        case GlassLook(veil=veil, lettering=lettering):
            assert veil.tint == ATTENTION and lettering.ink.color == "#ffffff"
        case other3:
            raise AssertionError(f"Glass preference produced {other3}")
    match look(appearance.Material.SOLID, appearance.Frost.SMOKED, Tint.ATTENTION):
        case SolidLook(fill=fill):
            assert fill == Shade(ATTENTION)
        case other4:
            raise AssertionError(f"Solid preference produced {other4}")
    contrast = appearance.Contrast("#000000", "#ffff00")
    match (look(contrast, appearance.Frost.SMOKED, Tint.NONE), look(contrast, appearance.Frost.SMOKED, Tint.ATTENTION)):
        case (SolidLook(fill=Shade("#000000"), lettering=resting), SolidLook(fill=Shade("#ffff00"), lettering=asking)):
            assert resting.ink.color == "#ffff00" and asking.ink.color == "#000000"
        case other5:
            raise AssertionError(f"High contrast produced {other5}")


def test_high_contrast_keeps_every_reading_in_the_system_foreground() -> None:
    # Defect: the microphone or a low battery keeps Workspace's colours under high contrast.
    contrast = look(appearance.Contrast("#000000", "#ffff00"), appearance.Frost.SMOKED, Tint.NONE).lettering
    assert {reading(contrast, tone, contrast=True) for tone in Tone} == {contrast.ink}
    glass = look(appearance.Material.GLASS, appearance.Frost.LIGHT, Tint.NONE).lettering
    assert reading(glass, Tone.LOW, contrast=False) != glass.ink
