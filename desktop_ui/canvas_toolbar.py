"""The canvas toolbar's actions as data: `desktop_ui/spec/canvas.py`.

Everything the canvas does is reached from its toolbar, as the island bar's
controls are from its status capsule. The toolbar's row holds pinned actions, and
the selected bubble's pinned actions while one is selected. "More", or a right
click, expands the toolbar in place into titled sections of tiles about its
subject: the canvas, a bubble, or a relationship. There are no popup menus.

The spec orders the row and the sections and gives each tile its words and
symbol. What an action does, when it applies (work-thread actions on a work
thread, Rename on a group, Relationships while a bubble has any) and wording that
follows state stay typed here and in the canvas panel. The toolbar reads the
spec each time it shows, so an edit shows on the next selection or expansion.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum, auto
from typing import Final, assert_never

from desktop_ui.fluent_icons import REGULAR


class CanvasTool(StrEnum):
    """What the canvas as a whole does."""

    CENTER = auto()
    CONTENTS = auto()  # Collapse containers or show group contents, by the current mode.
    ARRANGE_THREADS = auto()
    ARRANGE_ALL = auto()
    REFRESH = auto()
    NEW_CONTEXT = auto()
    NEW_GROUP = auto()
    NOTE = auto()
    DOCUMENT = auto()
    DOCUMENT_LINK = auto()
    WEB_REFERENCE = auto()
    CONNECT_SOURCE = auto()
    CHOOSE_GROUP = auto()
    MAXIMIZE = auto()  # The canvas window's own.
    CLOSE = auto()


class BubbleAction(StrEnum):
    """What a selected bubble does."""

    FOCUS = auto()
    CONTENTS = auto()
    CONNECT = auto()
    CONTINUE = auto()  # Work threads only, like the three after it.
    EDIT_WORK = auto()
    DISMISS = auto()
    NOT_MINE = auto()
    RENAME_GROUP = auto()  # Groups only.
    PUT_INSIDE = auto()
    MOVE_TO_CANVAS = auto()
    RELATIONSHIPS = auto()  # A tile per relationship, while the bubble has any.


class RelationAction(StrEnum):
    """What a right-clicked relationship does."""

    EDIT = auto()
    REMOVE = auto()


WORK_ONLY: Final = frozenset({BubbleAction.CONTINUE, BubbleAction.EDIT_WORK, BubbleAction.DISMISS, BubbleAction.NOT_MINE})


@dataclass(frozen=True, slots=True)
class CanvasItem:
    action: CanvasTool
    label: str = ""
    """Its words; `contents` words the canvas's mode itself."""
    icon: str = ""


@dataclass(frozen=True, slots=True)
class BubbleItem:
    action: BubbleAction
    label: str = ""
    icon: str = ""


@dataclass(frozen=True, slots=True)
class RelationItem:
    action: RelationAction
    label: str = ""
    icon: str = ""


@dataclass(frozen=True, slots=True)
class Row:
    """The toolbar's row, between the voice hint and Find."""

    canvas: tuple[CanvasItem, ...]
    bubble: tuple[BubbleItem, ...]
    """Shown after the canvas's while a bubble is selected."""


@dataclass(frozen=True, slots=True)
class CanvasSection:
    title: str
    items: tuple[CanvasItem, ...]


@dataclass(frozen=True, slots=True)
class BubbleSection:
    """The selected bubble's actions, titled with its name; only while one is selected."""

    items: tuple[BubbleItem, ...]


@dataclass(frozen=True, slots=True)
class RelationSection:
    """A right-clicked relationship's actions, titled with its reason."""

    items: tuple[RelationItem, ...]


@dataclass(frozen=True, slots=True)
class DismissedSection:
    """A tile to restore each dismissed work thread, while there are any."""

    title: str
    icon: str


type Section = CanvasSection | BubbleSection | RelationSection | DismissedSection


@dataclass(frozen=True, slots=True)
class CanvasToolbarSpec:
    """`spec/canvas.py`: the toolbar's row and its expanded sections, top to bottom."""

    row: Row
    sections: tuple[Section, ...]


def item_problems(place: str, item: CanvasItem | BubbleItem | RelationItem) -> tuple[str, ...]:
    """What's wrong with one item where it is placed."""
    stated = (isinstance(item, CanvasItem) and item.action is CanvasTool.CONTENTS) or (
        isinstance(item, BubbleItem) and item.action is BubbleAction.RELATIONSHIPS
    )
    return (
        *((f"{place}: {item.action} needs a label",) if not stated and not item.label else ()),
        *((f"{place}: {item.action} takes no label: its words follow what it shows",) if stated and item.label else ()),
        *((f"{place}: {item.action} needs an icon from the symbol set, not {item.icon!r}",) if item.icon not in REGULAR else ()),
    )


def toolbar_problems(spec: CanvasToolbarSpec) -> tuple[str, ...]:
    """What makes the spec unusable beyond its shape, each named by where it is."""
    expanded = tuple(item for section in spec.sections if not isinstance(section, DismissedSection) for item in section.items)
    # Canvas, bubble and relationship actions share names (`contents`), so each kind counts its own.
    actions = tuple((type(item).__name__, str(item.action)) for item in expanded)
    return (
        *(f"sections: {action} appears more than once" for kind, action in sorted(set(actions)) if actions.count((kind, action)) > 1),
        *(problem for item in (*spec.row.canvas, *spec.row.bubble) for problem in item_problems("row", item)),
        *(problem for item in expanded for problem in item_problems("sections", item)),
        *(
            f"sections: {section.title} needs an icon from the symbol set"
            for section in spec.sections
            if isinstance(section, DismissedSection) and section.icon not in REGULAR
        ),
        *(
            f"sections: more than one {kind.__name__}"
            for kind in (BubbleSection, RelationSection, DismissedSection)
            if sum(isinstance(section, kind) for section in spec.sections) > 1
        ),
    )


# ---- what the toolbar shows ------------------------------------------------------------


class Kind(StrEnum):
    WORK = auto()
    GROUP = auto()
    OTHER = auto()


@dataclass(frozen=True, slots=True)
class Bubble:
    """A selected bubble, as far as its actions depend on it."""

    identity: str
    title: str
    kind: Kind


@dataclass(frozen=True, slots=True)
class Relationship:
    index: int
    """Its place among the canvas's relationships."""
    reason: str


type Subject = Bubble | Relationship | None
"""What the toolbar is about: a bubble, a relationship, or the whole canvas."""


@dataclass(frozen=True, slots=True)
class OnCanvas:
    action: CanvasTool


@dataclass(frozen=True, slots=True)
class OnBubble:
    action: BubbleAction
    identity: str


@dataclass(frozen=True, slots=True)
class OnRelationship:
    action: RelationAction
    index: int


@dataclass(frozen=True, slots=True)
class Restore:
    work: str


@dataclass(frozen=True, slots=True)
class Open:
    """A relationship's tile in its bubble's section: the toolbar turns to that relationship."""

    relationship: Relationship


type Act = OnCanvas | OnBubble | OnRelationship | Restore | Open


@dataclass(frozen=True, slots=True)
class Tile:
    label: str
    icon: str
    act: Act


@dataclass(frozen=True, slots=True)
class Group:
    title: str
    tiles: tuple[Tile, ...]


@dataclass(frozen=True, slots=True)
class Dismissed:
    work: str
    title: str


def contents_label(*, collapsed: bool) -> str:
    return "Show group contents" if collapsed else "Collapse containers"


def canvas_tile(item: CanvasItem, *, collapsed: bool) -> Tile:
    label = contents_label(collapsed=collapsed) if item.action is CanvasTool.CONTENTS else item.label
    return Tile(label, item.icon, OnCanvas(item.action))


def applies(action: BubbleAction, bubble: Bubble, *, related: bool) -> bool:
    match action:
        case BubbleAction.CONTINUE | BubbleAction.EDIT_WORK | BubbleAction.DISMISS | BubbleAction.NOT_MINE:
            return bubble.kind is Kind.WORK
        case BubbleAction.RENAME_GROUP:
            return bubble.kind is Kind.GROUP
        case BubbleAction.RELATIONSHIPS:
            return related
        case BubbleAction.FOCUS | BubbleAction.CONTENTS | BubbleAction.CONNECT | BubbleAction.PUT_INSIDE | BubbleAction.MOVE_TO_CANVAS:
            return True
        case _:
            assert_never(action)


def item_tiles(item: BubbleItem, bubble: Bubble, relationships: Sequence[Relationship]) -> tuple[Tile, ...]:
    """One item's tiles: none if it doesn't apply, a tile per relationship for Relationships."""
    if not applies(item.action, bubble, related=bool(relationships)):
        return ()
    if item.action is BubbleAction.RELATIONSHIPS:
        return tuple(Tile(each.reason, item.icon, Open(each)) for each in relationships)
    return (Tile(item.label, item.icon, OnBubble(item.action, bubble.identity)),)


def bubble_tiles(items: Sequence[BubbleItem], bubble: Bubble, relationships: Sequence[Relationship]) -> tuple[Tile, ...]:
    """The bubble's tiles; Relationships becomes a tile per relationship."""
    return tuple(tile for item in items for tile in item_tiles(item, bubble, relationships))


def row(spec: CanvasToolbarSpec, subject: Subject, relationships: Sequence[Relationship], *, collapsed: bool) -> tuple[Tile, ...]:
    """The pinned tiles in the toolbar's row now; `relationships` are the selected bubble's."""
    canvas = tuple(canvas_tile(item, collapsed=collapsed) for item in spec.row.canvas)
    match subject:
        case Bubble():
            return (*canvas, *bubble_tiles(spec.row.bubble, subject, relationships))
        case Relationship() | None:
            return canvas
        case _:
            assert_never(subject)


def group(
    section: Section,
    subject: Subject,
    relationships: Sequence[Relationship],
    dismissed: Sequence[Dismissed],
    *,
    collapsed: bool,
) -> Group | None:
    """`section`'s group now; None for a section about another kind of subject."""
    match section:
        case CanvasSection(title=title, items=items):
            return Group(title, tuple(canvas_tile(item, collapsed=collapsed) for item in items))
        case BubbleSection(items=items) if isinstance(subject, Bubble):
            return Group(subject.title, bubble_tiles(items, subject, relationships))
        case RelationSection(items=items) if isinstance(subject, Relationship):
            return Group(subject.reason, tuple(Tile(item.label, item.icon, OnRelationship(item.action, subject.index)) for item in items))
        case DismissedSection(title=title, icon=symbol):
            return Group(title, tuple(Tile("Restore · " + each.title, symbol, Restore(each.work)) for each in dismissed))
        case BubbleSection() | RelationSection():
            return None  # Not about this subject.
        case _:
            assert_never(section)


def sections(
    spec: CanvasToolbarSpec,
    subject: Subject,
    relationships: Sequence[Relationship],
    dismissed: Sequence[Dismissed],
    *,
    collapsed: bool,
) -> tuple[Group, ...]:
    """The expanded toolbar's groups now, top to bottom; a group with no tiles is left out.
    `relationships` are the selected bubble's."""
    shown = (group(section, subject, relationships, dismissed, collapsed=collapsed) for section in spec.sections)
    return tuple(each for each in shown if each is not None and each.tiles)
