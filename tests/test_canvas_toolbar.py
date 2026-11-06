"""The canvas toolbar: what its row and its expanded sections offer, from canvas.toml."""

from pathlib import Path

from desktop_ui import ui_spec
from desktop_ui.canvas_toolbar import (
    Bubble,
    BubbleAction,
    BubbleSection,
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
)
from desktop_ui.ui_spec import SHIPPED, SpecError

SPEC = ui_spec.canvas_toolbar()
TEXT = (SHIPPED / ui_spec.CANVAS_FILE).read_text(encoding="utf-8")
WORK = Bubble("work-1", "Budget review", Kind.WORK)
GROUP = Bubble("group-1", "Q3", Kind.GROUP)


def acts(subject: Bubble | Relationship | None, relationships: tuple[Relationship, ...] = (), dismissed: tuple[Dismissed, ...] = ()) -> list[object]:
    return [tile.act for group in sections(SPEC, subject, relationships, dismissed, collapsed=False) for tile in group.tiles]


def test_every_canvas_action_is_reachable_from_the_shipped_toolbar() -> None:
    # Defect: an edit to canvas.toml drops an action, so the canvas can no longer do it.
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


def refused(tmp_path: Path, edited: str) -> str:
    tmp_path.mkdir(parents=True)
    (tmp_path / ui_spec.CANVAS_FILE).write_text(edited, encoding="utf-8")
    try:
        ui_spec.canvas_toolbar(tmp_path)
    except SpecError as error:
        return str(error)
    raise AssertionError("The canvas toolbar spec was accepted.")


def test_toolbar_edits_that_repeat_misword_or_misname_a_tile_are_refused(tmp_path: Path) -> None:
    # Defect: an action placed twice runs twice, a tile shows no words, the mode
    # toggle's label hides its state, or an unknown symbol draws a placeholder.
    twice = TEXT.replace('{ action = "new_group", label = "Group", icon = "grid" }', '{ action = "note", label = "Group", icon = "grid" }')
    assert "note appears more than once" in refused(tmp_path / "twice", twice)
    assert "center needs a label" in refused(
        tmp_path / "bare", TEXT.replace('{ action = "center", label = "Center", icon = "center" }', '{ action = "center", icon = "center" }')
    )
    assert "contents takes no label" in refused(
        tmp_path / "stated", TEXT.replace('{ action = "contents", icon = "layers" }', '{ action = "contents", label = "Contents", icon = "layers" }')
    )
    assert "not 'sparkle'" in refused(
        tmp_path / "symbol", TEXT.replace('label = "Add a note", icon = "plus"', 'label = "Add a note", icon = "sparkle"')
    )
