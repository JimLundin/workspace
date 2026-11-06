"""The canvas toolbar: what its row and its expanded sections offer, from spec/canvas.py."""

from dataclasses import replace

from desktop_ui.canvas_toolbar import (
    Bubble,
    BubbleAction,
    BubbleSection,
    CanvasItem,
    CanvasSection,
    CanvasTool,
    Dismissed,
    Kind,
    OnBubble,
    OnCanvas,
    OnRelationship,
    Open,
    RelationAction,
    RelationSection,
    Relationship,
    Restore,
    row,
    sections,
    toolbar_problems,
)
from desktop_ui.spec.canvas import CANVAS

SPEC = CANVAS
WORK = Bubble("work-1", "Budget review", Kind.WORK)
GROUP = Bubble("group-1", "Q3", Kind.GROUP)


def acts(subject: Bubble | Relationship | None, relationships: tuple[Relationship, ...] = (), dismissed: tuple[Dismissed, ...] = ()) -> list[object]:
    return [tile.act for group in sections(SPEC, subject, relationships, dismissed, collapsed=False) for tile in group.tiles]


def test_every_canvas_action_is_reachable_from_the_shipped_toolbar() -> None:
    # Defect: an edit to the canvas spec drops an action, so the canvas can no longer do it.
    canvas = {item.action for section in SPEC.sections if isinstance(section, CanvasSection) for item in section.items}
    bubble = {item.action for section in SPEC.sections if isinstance(section, BubbleSection) for item in section.items}
    relation = {item.action for section in SPEC.sections if isinstance(section, RelationSection) for item in section.items}
    assert (canvas, bubble, relation) == (set(CanvasTool), set(BubbleAction), set(RelationAction))


def test_the_expanded_toolbar_offers_only_what_applies_to_its_subject() -> None:
    # Defects: a group offers Continue with agent, a work thread offers Rename group,
    # the canvas alone shows a bubble's or relationship's tiles, or an empty
    # Dismissed section takes room.
    work = acts(WORK)
    assert OnBubble(BubbleAction.CONTINUE, WORK.identity) in work and OnBubble(BubbleAction.RENAME_GROUP, WORK.identity) not in work
    group = acts(GROUP)
    assert OnBubble(BubbleAction.RENAME_GROUP, GROUP.identity) in group and OnBubble(BubbleAction.CONTINUE, GROUP.identity) not in group
    alone = acts(None)
    assert not any(isinstance(act, OnBubble | OnRelationship | Restore) for act in alone) and OnCanvas(CanvasTool.NOTE) in alone
    assert Restore("w9") in acts(None, dismissed=(Dismissed("w9", "Old"),))
    titles = [group.title for group in sections(SPEC, WORK, (), (), collapsed=False)]
    assert titles[0] == "Budget review" and "Dismissed work" not in titles


def test_a_bubbles_relationships_open_their_own_actions() -> None:
    # Defect: a relationship tile acts on the wrong relationship, or a right-clicked
    # relationship shows no Edit and Remove for itself.
    linked = (Relationship(3, "Feeds into Q3"),)
    assert Open(linked[0]) in acts(WORK, linked)
    on = acts(linked[0])
    assert OnRelationship(RelationAction.EDIT, 3) in on and OnRelationship(RelationAction.REMOVE, 3) in on
    assert sections(SPEC, linked[0], (), (), collapsed=False)[0].title == "Feeds into Q3"


def test_the_row_pins_the_selected_bubbles_actions_and_the_mode_toggle_words_its_state() -> None:
    # Defects: selecting a bubble leaves the row unchanged, or Collapse containers
    # keeps its words after the canvas has collapsed.
    assert len(row(SPEC, WORK, (), collapsed=False)) > len(row(SPEC, None, (), collapsed=False))
    contents = [
        tile.label for group in sections(SPEC, None, (), (), collapsed=True) for tile in group.tiles if tile.act == OnCanvas(CanvasTool.CONTENTS)
    ]
    assert contents == ["Show group contents"]


def added(*items: CanvasItem) -> tuple[str, ...]:
    """The problems with the shipped toolbar plus one more section of `items`."""
    return toolbar_problems(replace(SPEC, sections=(*SPEC.sections, CanvasSection("Extra", items))))


def test_toolbar_edits_that_repeat_misword_or_misname_a_tile_are_refused() -> None:
    # Defect: an action placed twice runs twice, a tile shows no words, the mode
    # toggle's label hides its state, or an unknown symbol draws a placeholder.
    assert "sections: note appears more than once" in added(CanvasItem(CanvasTool.NOTE, "Note", "doc"))
    bare = replace(SPEC, row=replace(SPEC.row, canvas=(CanvasItem(CanvasTool.CENTER, icon="center"),)))
    assert "row: center needs a label" in toolbar_problems(bare)
    stated = replace(SPEC, row=replace(SPEC.row, canvas=(CanvasItem(CanvasTool.CONTENTS, "Contents", "layers"),)))
    assert any("contents takes no label" in each for each in toolbar_problems(stated))
    symbol = replace(SPEC, row=replace(SPEC.row, canvas=(CanvasItem(CanvasTool.NOTE, "Add a note", "sparkle"),)))
    assert any("not 'sparkle'" in each for each in toolbar_problems(symbol))
