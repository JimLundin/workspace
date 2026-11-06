"""The canvas's right-click menus as data: `desktop_ui/spec/canvas.toml`.

The spec orders each menu's actions, gives their words, groups them into one level
of submenus and separates them. What an action does, when it applies (work-thread
actions on a work thread, Rename on a group, Relationships while there are any)
and wording that follows state stay in the canvas panel. Each menu is built
from the spec as it opens, so an edit shows on the next right-click.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum, auto
from typing import Final, Literal, assert_never

from pydantic import ConfigDict

_SPEC = ConfigDict(extra="forbid")


class BackgroundAction(StrEnum):
    """The canvas background's menu."""

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
    DISMISSED = auto()  # A submenu of dismissed work to restore.
    CONNECT_SOURCE = auto()
    CHOOSE_GROUP = auto()


class BubbleAction(StrEnum):
    """A bubble's menu."""

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
    RELATIONSHIPS = auto()  # A submenu of the bubble's relationships, while it has any.


STATED: Final = frozenset({BackgroundAction.CONTENTS})
"""Actions whose words follow state, so the spec gives them none."""


@dataclass(frozen=True, slots=True)
class Separator:
    separator: Literal[True]
    __pydantic_config__ = _SPEC


@dataclass(frozen=True, slots=True)
class BackgroundItem:
    action: BackgroundAction
    label: str = ""
    __pydantic_config__ = _SPEC


@dataclass(frozen=True, slots=True)
class BackgroundMenu:
    menu: str
    items: tuple[BackgroundItem | Separator, ...]
    __pydantic_config__ = _SPEC


@dataclass(frozen=True, slots=True)
class BubbleItem:
    action: BubbleAction
    label: str = ""
    __pydantic_config__ = _SPEC


@dataclass(frozen=True, slots=True)
class BubbleMenu:
    menu: str
    items: tuple[BubbleItem | Separator, ...]
    __pydantic_config__ = _SPEC


type Background = BackgroundItem | BackgroundMenu | Separator
type Bubble = BubbleItem | BubbleMenu | Separator


@dataclass(frozen=True, slots=True)
class CanvasMenus:
    """`canvas.toml`: the background's menu and a bubble's, top to bottom."""

    background: tuple[Background, ...]
    bubble: tuple[Bubble, ...]
    __pydantic_config__ = _SPEC


def flat(items: Sequence[Background | Bubble]) -> tuple[BackgroundItem | BubbleItem, ...]:
    """Every action item, submenus opened."""
    found: list[BackgroundItem | BubbleItem] = []
    for item in items:
        match item:
            case BackgroundMenu(items=inner) | BubbleMenu(items=inner):
                found.extend(each for each in inner if not isinstance(each, Separator))
            case BackgroundItem() | BubbleItem():
                found.append(item)
            case Separator():
                pass
            case _:
                assert_never(item)
    return tuple(found)


def menu_problems(spec: CanvasMenus) -> tuple[str, ...]:
    """What makes the menus unusable beyond their shape: an action twice, a label missing or not allowed."""
    found: list[str] = []
    for name, items in (("background", flat(spec.background)), ("bubble", flat(spec.bubble))):
        actions = [item.action for item in items]
        found.extend(f"{name}: {action} appears more than once" for action in sorted(set(actions)) if actions.count(action) > 1)
        for item in items:
            match item:
                case BackgroundItem(action=action, label=label) | BubbleItem(action=action, label=label):
                    stated = name == "background" and action in STATED
                    if stated and label:
                        found.append(f"{name}: {action} takes no label: its words follow the canvas's mode")
                    if not stated and not label:
                        found.append(f"{name}: {action} needs a label")
                case _:
                    assert_never(item)
    return tuple(found)
