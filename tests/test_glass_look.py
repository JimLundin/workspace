"""How shared glass surfaces read under each material and their owner's observations."""

from desktop_ui.colour import Rgb
from desktop_ui.components.appearance import (
    Attention,
    CanvasBar,
    Capsule,
    FrostLook,
    Glass,
    GlassLook,
    Lettering,
    Look,
    Menu,
    Rim,
    Scheme,
    Shade,
    SolidLook,
    Tokens,
    look,
    reading,
)
from desktop_ui.components.meaning import Tint, Tone
from winapi import appearance


def scheme_tokens(scheme: Scheme, ink: str, solid: str) -> Tokens:
    return Tokens(
        scheme=scheme,
        ink=Shade(ink, 0.9),
        ink2=Shade(ink, 0.5),
        ink3=Shade(ink, 0.3),
        fill=Shade(ink, 0.05),
        hover=Shade(ink, 0.1),
        press=Shade(ink, 0.2),
        separator=Shade(ink, 0.1),
        solid=solid,
        solid_edge=Shade(ink, 0.1),
        window=solid,
        thumb=Shade(ink, 0.4),
        canvas_bar_veil=Shade(solid, 0.8),
        rim=Rim(0.5, 0.1, 0.2),
        segment=solid,
    )


GLASS = Glass(
    tokens=frozendict(
        {Scheme.DARK: scheme_tokens(Scheme.DARK, "#f0f0f0", "#202020"), Scheme.LIGHT: scheme_tokens(Scheme.LIGHT, "#101010", "#fafafa")}
    ),
    frosts=frozendict(
        {
            appearance.Frost.BRIGHT: FrostLook(Scheme.LIGHT, Shade("#fafafa", 0.3), 0.1),
            appearance.Frost.LIGHT: FrostLook(Scheme.DARK, Shade("#202020", 0.3), 0.3),
            appearance.Frost.SMOKED: FrostLook(Scheme.DARK, Shade("#202020", 0.5), 0.3),
        }
    ),
    attention=Attention(
        hue="#e07000",
        veil=0.85,
        canvas_veil=0.9,
        rim=Rim(0.5, 0.1, 0.1),
        lettering=Lettering(Shade("#ffffff"), Shade("#ffffff", 0.8), Shade("#ffffff", 0.2), Shade("#ffffff", 0.3)),
        solid_edge=Shade("#ffffff", 0.2),
    ),
    menu_veil=0.7,
    contrast_hover=0.25,
    contrast_press=0.4,
    rim_light="#ffffff",
    rim_fall=0.3,
    rim_rise=0.7,
)
"""The test's own material."""


def material(preference: appearance.Preference, pane: Capsule | Menu | CanvasBar, tint: Tint) -> Look:
    return look(preference, pane, tint, GLASS)


def brightness(color: str) -> int:
    rgb = Rgb.parse(color)
    return rgb.red + rgb.green + rgb.blue


def test_glass_takes_its_scheme_and_veil_from_the_desktop_behind_it() -> None:
    # Defects: white ink stays on glass over a bright desktop, or a busy desktop
    # gets the thin veil and small text loses contrast.
    match (
        material(appearance.Material.GLASS, Capsule(appearance.Frost.BRIGHT), Tint.NONE),
        material(appearance.Material.GLASS, Capsule(appearance.Frost.SMOKED), Tint.NONE),
    ):
        case (GlassLook(lettering=over_bright), GlassLook(lettering=over_dark)):
            assert brightness(over_bright.ink.color) < brightness(over_dark.ink.color)
        case other1:
            raise AssertionError(f"Glass preference produced {other1}")
    match (
        material(appearance.Material.GLASS, Capsule(appearance.Frost.LIGHT), Tint.NONE),
        material(appearance.Material.GLASS, Capsule(appearance.Frost.SMOKED), Tint.NONE),
    ):
        case (GlassLook(veil=thin), GlassLook(veil=heavy)):
            assert heavy.opacity > thin.opacity and heavy.color == thin.color
        case other2:
            raise AssertionError(f"Glass preference produced {other2}")


def test_attention_keeps_its_meaning_under_every_material() -> None:
    # Defects: a waiting question looks like the resting island when transparency
    # is off, or high contrast drops the distinction entirely.
    def both(preference: appearance.Material, frost: appearance.Frost) -> tuple[Look, Look]:
        return material(preference, Capsule(frost), Tint.NONE), material(preference, Capsule(frost), Tint.ATTENTION)

    for frost in appearance.Frost:
        match both(appearance.Material.GLASS, frost):
            case (GlassLook(veil=resting_veil), GlassLook(veil=asking_veil)):
                assert asking_veil.color != resting_veil.color
            case other3:
                raise AssertionError(f"Glass preference produced {other3}")
        match both(appearance.Material.SOLID, frost):
            case (SolidLook(fill=resting_fill), SolidLook(fill=asking_fill)):
                assert asking_fill != resting_fill
            case other4:
                raise AssertionError(f"Solid preference produced {other4}")
    contrast = appearance.Contrast("#000000", "#ffff00")
    match (material(contrast, Capsule(appearance.Frost.SMOKED), Tint.NONE), material(contrast, Capsule(appearance.Frost.SMOKED), Tint.ATTENTION)):
        case (SolidLook(fill=Shade("#000000"), lettering=resting), SolidLook(fill=Shade("#ffff00"), lettering=asking)):
            assert resting.ink.color == "#ffff00" and asking.ink.color == "#000000"
        case other5:
            raise AssertionError(f"High contrast produced {other5}")


def test_high_contrast_keeps_every_reading_in_the_system_foreground() -> None:
    # Defect: the microphone or a low battery keeps Workspace's colours under high contrast.
    contrast = material(appearance.Contrast("#000000", "#ffff00"), Capsule(appearance.Frost.SMOKED), Tint.NONE).lettering
    assert {reading(contrast, tone, contrast=True) for tone in Tone} == {contrast.ink}
    glass = material(appearance.Material.GLASS, Capsule(appearance.Frost.LIGHT), Tint.NONE).lettering
    assert reading(glass, Tone.LOW, contrast=False) != glass.ink


def test_the_scheme_owned_pane_uses_system_ink_under_high_contrast() -> None:
    # Defect: routing a large surface through the recipe bypasses high contrast
    # and retains Workspace's veil or translucent text instead of system colours.
    contrast = appearance.Contrast("#000000", "#ffff00")
    for scheme in Scheme:
        match material(contrast, CanvasBar(scheme), Tint.NONE):
            case SolidLook(fill=fill, edge=edge, lettering=ink):
                assert fill == Shade(contrast.background)
                assert edge == ink.ink == ink.quiet == Shade(contrast.foreground)
            case other:
                raise AssertionError(f"High contrast produced {other}")


def test_reduce_transparency_gives_a_scheme_owned_pane_its_solid_surface() -> None:
    # Defect: a scheme-owned pane keeps glass when transparency is disabled, or falls back
    # to one fixed surface instead of its own app scheme.
    solids = tuple(material(appearance.Material.SOLID, CanvasBar(scheme), Tint.NONE) for scheme in Scheme)
    assert all(isinstance(each, SolidLook) for each in solids)
    assert len({each.fill for each in solids if isinstance(each, SolidLook)}) == len(Scheme)
    assert len({each.lettering.ink for each in solids}) == len(Scheme)


def test_expanded_menu_glass_is_thicker_than_its_capsule() -> None:
    # Defect: expansion reuses the capsule's thin veil or changes its colour,
    # reducing the menu's text contrast over the same observed desktop.
    for frost in appearance.Frost:
        match (material(appearance.Material.GLASS, Capsule(frost), Tint.NONE), material(appearance.Material.GLASS, Menu(frost), Tint.NONE)):
            case GlassLook(veil=small), GlassLook(veil=large):
                assert large.opacity > small.opacity and large.color == small.color
            case other:
                raise AssertionError(f"Glass preference produced {other}")
