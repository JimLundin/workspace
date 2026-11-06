"""The canvas toolbar: everything the canvas does starts here.

The toolbar's row holds the pinned tiles below, then, while a bubble is selected,
that bubble's. "More", or a right click on a bubble or a relationship, expands the
toolbar in place into the sections below, top to bottom; Escape or "More"
collapses it. A section with nothing to show now is left out.

Each tile names an action, its words and its symbol (from `fluent_icons`). Each
action appears once across the sections. `CanvasTool.CONTENTS` words the canvas's
mode and `BubbleAction.RELATIONSHIPS` becomes a tile per relationship, so neither
takes a label. The bubble section is titled with the selected bubble's name and
the relationship section with its reason.
"""

from typing import Final

from desktop_ui.canvas_toolbar import (
    BubbleAction,
    BubbleItem,
    BubbleSection,
    CanvasItem,
    CanvasSection,
    CanvasTool,
    CanvasToolbarSpec,
    DismissedSection,
    RelationAction,
    RelationItem,
    RelationSection,
    Row,
)

CANVAS: Final = CanvasToolbarSpec(
    row=Row(
        canvas=(CanvasItem(CanvasTool.NOTE, "Add a note", "plus"),),
        bubble=(
            BubbleItem(BubbleAction.FOCUS, "Focus bubble", "center"),
            BubbleItem(BubbleAction.CONTINUE, "Continue with agent", "agent"),
            BubbleItem(BubbleAction.CONNECT, "Connect to another bubble…", "link"),
        ),
    ),
    sections=(
        BubbleSection(
            (
                BubbleItem(BubbleAction.FOCUS, "Focus", "center"),
                BubbleItem(BubbleAction.CONTENTS, "Show / hide contents", "expand"),
                BubbleItem(BubbleAction.CONNECT, "Connect…", "link"),
                BubbleItem(BubbleAction.CONTINUE, "Continue with agent", "agent"),
                BubbleItem(BubbleAction.EDIT_WORK, "Edit work context", "doc"),
                BubbleItem(BubbleAction.DISMISS, "Dismiss work", "close"),
                BubbleItem(BubbleAction.NOT_MINE, "This isn't my work", "park"),
                BubbleItem(BubbleAction.RENAME_GROUP, "Rename group", "doc"),
                BubbleItem(BubbleAction.PUT_INSIDE, "Put inside…", "layers"),
                BubbleItem(BubbleAction.MOVE_TO_CANVAS, "Move to canvas", "canvas"),
                BubbleItem(BubbleAction.RELATIONSHIPS, icon="link"),
            )
        ),
        RelationSection(
            (
                RelationItem(RelationAction.EDIT, "Edit relationship…", "doc"),
                RelationItem(RelationAction.REMOVE, "Remove relationship", "close"),
            )
        ),
        CanvasSection(
            "Add",
            (
                CanvasItem(CanvasTool.NEW_CONTEXT, "Work context", "plus"),
                CanvasItem(CanvasTool.NEW_GROUP, "Group", "grid"),
                CanvasItem(CanvasTool.NOTE, "Note", "doc"),
                CanvasItem(CanvasTool.DOCUMENT, "Document…", "doc"),
                CanvasItem(CanvasTool.DOCUMENT_LINK, "Document link…", "link"),
                CanvasItem(CanvasTool.WEB_REFERENCE, "Web reference…", "globe"),
            ),
        ),
        CanvasSection(
            "Arrange",
            (
                CanvasItem(CanvasTool.CENTER, "Center", "center"),
                CanvasItem(CanvasTool.CONTENTS, icon="layers"),
                CanvasItem(CanvasTool.ARRANGE_THREADS, "Arrange threads", "grid"),
                CanvasItem(CanvasTool.ARRANGE_ALL, "Arrange all", "table"),
                CanvasItem(CanvasTool.REFRESH, "Refresh sources", "refresh"),
            ),
        ),
        CanvasSection(
            "Connections",
            (
                CanvasItem(CanvasTool.CONNECT_SOURCE, "Connect source", "link"),
                CanvasItem(CanvasTool.CHOOSE_GROUP, "Put selection inside…", "layers"),
            ),
        ),
        CanvasSection(
            "Window",
            (
                CanvasItem(CanvasTool.MAXIMIZE, "Maximize or restore", "expand"),
                CanvasItem(CanvasTool.CLOSE, "Close canvas", "close"),
            ),
        ),
        DismissedSection("Dismissed work", "refresh"),
    ),
)
