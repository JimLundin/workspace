from collections.abc import Iterator
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Final, assert_never

from contracts.recording_state import RecordingAction, RecordingState
from contracts.status import Job
from desktop_ui import island_menu
from desktop_ui.ambient import Ambient, SystemStatus
from desktop_ui.application_observer import EMPTY_ARRANGEMENT, Arrangement
from desktop_ui.components.appearance import Glass, Palette, Washes
from desktop_ui.island_layout import Sizes
from desktop_ui.island_menu import (
    DISMISSED,
    Applied,
    Chosen,
    Command,
    Controls,
    ControlsSpec,
    Join,
    Menu,
    Page,
    Panel,
    Slider,
    ToolChoice,
    Trace,
    TrayChoice,
    Volume,
    entries,
    restores_focus,
    traced,
)
from desktop_ui.island_model import (
    Action,
    CapsuleView,
    IslandSpec,
    Key,
    Marker,
    capture,
    gigabytes,
    memory_used,
    usage,
)
from desktop_ui.island_motion import (
    IslandMotion,
    Springs,
    Timing,
    advance,
    finish,
    settled,
)
from desktop_ui.month import Month
from desktop_ui.navigation import Order, Placing
from protocol import Tool
from winapi import appearance
from winapi.machine_status import Memory, PowerUnavailable, Speakers
from winapi.shapes import Rect
from winapi.tray_host import Click

NO_SCREEN: Final = Rect(0, 0, 0, 0)
"""Before the first tick reads the primary screen."""


@dataclass(frozen=True, slots=True)
class Surroundings:
    system: SystemStatus = field(default_factory=SystemStatus)
    ambient: Ambient = field(
        default_factory=lambda: Ambient("", PowerUnavailable.UNKNOWN)
    )
    preference: appearance.Preference = appearance.Material.SOLID
    frost: appearance.Frost = appearance.Frost.SMOKED
    arrangement: Arrangement = EMPTY_ARRANGEMENT
    dark_when_away: bool | None = None
    """Whether screens go dark while away; None without the native shell."""
    tray_tips: tuple[str, ...] = ()
    screen: Rect = NO_SCREEN
    """The primary screen, which the bar spans."""
    scale: float = 1.0
    """The bar window's device pixels per DIP."""


@dataclass(frozen=True, slots=True, kw_only=True)
class BarSpec:
    island: IslandSpec
    controls: ControlsSpec
    springs: Springs
    timing: Timing
    sizes: Sizes
    glass: Glass
    palette: Palette
    washes: Washes
    hints: frozendict[Tool, str]
    """Each tool's keys on the layout the desktop is handed, which the menu shows beside its tools."""


@dataclass(frozen=True, slots=True)
class BarModel:
    spec: BarSpec
    closed: bool = False
    opened: Menu | None = None
    """The open panel, while there is one."""
    menu_target: int = 0
    """The window that had the keyboard before the menu opened."""
    hovered: Key | None = None
    dictating: bool = False
    overlay_enabled: bool = False
    job: Job | None = None
    recording: RecordingState = field(default_factory=RecordingState)
    chord_held: bool = False
    """Either keyboard is holding its Apps key."""
    layout_enabled: bool = True
    seen: Surroundings = field(default_factory=Surroundings)
    """What the tick last observed."""
    next_material: float = 0.0
    next_power: float = 0.0
    views: tuple[CapsuleView, ...] = ()
    motion: IslandMotion = field(default_factory=IslandMotion)
    """Reassigned each frame; the bar mutates no motion or view record."""
    last_frame: float | None = None
    sampled_at: float | None = None


def memory_trace(model: BarModel) -> Trace:
    system, status = model.seen.system, model.spec.island.status
    used = memory_used(system.memory, status).text
    match system.memory:
        case Memory(total=total):
            return traced(
                system.memory_history,
                total,
                f"{used} {model.spec.island.words.of} {gigabytes(total, status)}",
            )
        case None:
            return traced(system.memory_history, None, used)
        case _:
            assert_never(system.memory)


def menu(model: BarModel, panel: Panel) -> Menu:
    recorded = (
        capture(model.recording, model.spec.island.words.phases)
        if model.recording.capturing
        else None
    )
    seen = model.seen
    kept = (
        opened if (opened := model.opened) and opened.panel is panel else None
    )
    month = kept.month if kept else None
    sound = Slider(
        model.spec.controls.words.sound,
        seen.system.volume,
        muted=seen.system.speakers is Speakers.MUTED,
    )
    built = Menu(
        panel,
        entries(
            Controls(
                recorded.title if recorded is not None else None,
                layout=model.layout_enabled,
                overlay=model.overlay_enabled,
                placement_paused=seen.arrangement.paused,
                dark_when_away=seen.dark_when_away is True,
                sound=sound,
                tray=seen.tray_tips,
                hints=model.spec.hints,
                today=seen.ambient.today,
                networks=seen.system.networks,
                power=seen.ambient.power,
                cpu=traced(
                    seen.system.cpu_history,
                    100,
                    usage(seen.system.cpu, model.spec.island.status).text,
                ),
                memory=memory_trace(model),
                month=month,
            ),
            model.spec.controls,
            panel,
        ),
        month=month,
        anchor=kept.anchor if kept else None,
    )
    return replace(built, selected=kept.selected) if kept else built


@dataclass(frozen=True, slots=True)
class Pressed:
    action: Action


@dataclass(frozen=True, slots=True)
class PanelPressed:
    panel: Panel
    slot: int | None = None
    """The reading's slot in the status capsule, which the panel hangs under."""


@dataclass(frozen=True, slots=True)
class Paged:
    months: int


@dataclass(frozen=True, slots=True)
class Hovered:
    key: Key | None


@dataclass(frozen=True, slots=True)
class Selected:
    index: int


@dataclass(frozen=True, slots=True)
class Picked:
    index: int


@dataclass(frozen=True, slots=True)
class MenuKey:
    press: island_menu.Press


@dataclass(frozen=True, slots=True)
class Deactivated: ...


@dataclass(frozen=True, slots=True)
class VolumeSet:
    level: float


@dataclass(frozen=True, slots=True)
class TrayClicked:
    slot: int
    click: Click


@dataclass(frozen=True, slots=True)
class OverlayShown:
    enabled: bool


@dataclass(frozen=True, slots=True)
class DictationShown:
    active: bool


@dataclass(frozen=True, slots=True)
class JobShown:
    job: Job | None


@dataclass(frozen=True, slots=True)
class RecordingShown:
    recording: RecordingState


@dataclass(frozen=True, slots=True)
class LayoutShown:
    enabled: bool


type ActivityChange = (
    OverlayShown | DictationShown | JobShown | RecordingShown | LayoutShown
)


@dataclass(frozen=True, slots=True)
class ChordHeld:
    held: bool


@dataclass(frozen=True, slots=True)
class Opening:
    opened: Menu
    target: int | None


@dataclass(frozen=True, slots=True)
class Ticked:
    seen: Surroundings
    next_power: float
    next_material: float


@dataclass(frozen=True, slots=True)
class Retargeted:
    views: tuple[CapsuleView, ...]
    motion: IslandMotion
    opened: Menu | None


@dataclass(frozen=True, slots=True)
class Framed:
    motion: IslandMotion
    last_frame: float | None


@dataclass(frozen=True, slots=True)
class Sampled:
    at: float


@dataclass(frozen=True, slots=True)
class Closing:
    pass


type Event = (
    Pressed
    | PanelPressed
    | Paged
    | Hovered
    | Selected
    | Picked
    | MenuKey
    | Deactivated
    | VolumeSet
    | TrayClicked
    | ActivityChange
    | ChordHeld
    | Opening
    | Ticked
    | Retargeted
    | Framed
    | Sampled
    | Closing
)


@dataclass(frozen=True, slots=True)
class Render: ...


@dataclass(frozen=True, slots=True)
class Expand:
    opened: Menu
    remember: bool


@dataclass(frozen=True, slots=True)
class Release:
    target: int


@dataclass(frozen=True, slots=True)
class Record:
    action: RecordingAction


@dataclass(frozen=True, slots=True)
class Keyboard:
    pass


@dataclass(frozen=True, slots=True)
class Layout:
    pass


@dataclass(frozen=True, slots=True)
class Overlay:
    pass


@dataclass(frozen=True, slots=True)
class AllControls:
    pass


@dataclass(frozen=True, slots=True)
class UseTool:
    tool: Tool


@dataclass(frozen=True, slots=True)
class Navigate:
    order: Order


@dataclass(frozen=True, slots=True)
class ToggleAway:
    pass


class SettingsPage(StrEnum):
    NOTIFICATIONS = "ms-settings:notifications"
    WIFI = "ms-settings:network-wifi"
    LOCATION = "ms-settings:privacy-location"
    POWER = "ms-settings:batterysaver"


@dataclass(frozen=True, slots=True)
class OpenSettings:
    page: SettingsPage


@dataclass(frozen=True, slots=True)
class Survey:
    """What the open panel needs read: the Wi-Fi networks in range while `listing`, and each app's
    use at the panels' pace while `ranking`."""

    listing: bool = field(kw_only=True)
    ranking: bool = field(kw_only=True)


@dataclass(frozen=True, slots=True)
class JoinNetwork:
    profile: str


@dataclass(frozen=True, slots=True)
class SetVolume:
    level: float


@dataclass(frozen=True, slots=True)
class SetMute:
    muted: bool = field(kw_only=True)


@dataclass(frozen=True, slots=True)
class ClickTray:
    slot: int
    click: Click


@dataclass(frozen=True, slots=True)
class ShowHints:
    pass


type Effect = (
    Render
    | Expand
    | Release
    | Record
    | Keyboard
    | Layout
    | Overlay
    | AllControls
    | UseTool
    | Navigate
    | ToggleAway
    | OpenSettings
    | Survey
    | JoinNetwork
    | SetVolume
    | SetMute
    | ClickTray
    | ShowHints
)


def _closed(
    model: BarModel, *, restore: bool
) -> tuple[BarModel, tuple[Effect, ...]]:
    if model.opened is None:
        return model, ()
    return replace(model, opened=None), (
        Release(model.menu_target if restore else 0),
        Survey(listing=False, ranking=False),
        Render(),
    )


def _ran(
    model: BarModel, choice: island_menu.Choice
) -> tuple[BarModel, tuple[Effect, ...]]:
    match choice:
        case ToolChoice(tool=tool):
            return model, (UseTool(tool),)
        case Command.RECORD:
            return model, (Record("start"),)
        case Command.STOP_RECORDING:
            return model, (Record("stop"),)
        case Command.KEYMAP:
            return model, (Keyboard(),)
        case Command.LAYOUT:
            return model, (Layout(),)
        case Command.OVERLAY:
            return model, (Overlay(),)
        case Command.PLACEMENT:
            return model, (Navigate(Placing.TOGGLE_PAUSE),)
        case Command.DARK_WHEN_AWAY:
            return model, (ToggleAway(),)
        case Command.MUTE:
            return _muted(
                model, muted=model.seen.system.speakers is not Speakers.MUTED
            )
        case Command.THIS_MONTH:
            return _turned(model, None), ()
        case Page(months=months):
            return _paged(model, months), ()
        case Command.NOTIFICATIONS:
            return model, (OpenSettings(SettingsPage.NOTIFICATIONS),)
        case Command.WIFI_SETTINGS:
            return model, (OpenSettings(SettingsPage.WIFI),)
        case Command.LOCATION_SETTINGS:
            return model, (OpenSettings(SettingsPage.LOCATION),)
        case Command.POWER_SETTINGS:
            return model, (OpenSettings(SettingsPage.POWER),)
        case Join(profile=profile):
            return model, (JoinNetwork(profile),)
        case Command.ALL_CONTROLS:
            return model, (AllControls(),)
        case Volume(level=level):
            return _volume(model, level)
        case TrayChoice(slot=slot):
            return _tray(model, slot, Click.LEFT)
        case _:
            assert_never(choice)


def _volume(
    model: BarModel, level: float
) -> tuple[BarModel, tuple[Effect, ...]]:
    seen = replace(model.seen, system=replace(model.seen.system, volume=level))
    return replace(model, seen=seen), (SetVolume(level), Render())


def _muted(
    model: BarModel, *, muted: bool
) -> tuple[BarModel, tuple[Effect, ...]]:
    speakers = Speakers.MUTED if muted else Speakers.AUDIBLE
    seen = replace(
        model.seen, system=replace(model.seen.system, speakers=speakers)
    )
    return replace(model, seen=seen), (SetMute(muted=muted), Render())


def _turned(model: BarModel, month: Month | None) -> BarModel:
    return (
        replace(model, opened=replace(model.opened, month=month))
        if model.opened is not None
        else model
    )


def _paged(model: BarModel, months: int) -> BarModel:
    if not (opened := model.opened) or not (today := model.seen.ambient.today):
        return model
    try:
        return _turned(model, (opened.month or Month.of(today)).paged(months))
    except ValueError:
        return model


def _tray(
    model: BarModel, slot: int, click: Click
) -> tuple[BarModel, tuple[Effect, ...]]:
    model, closing = _closed(model, restore=False)
    return model, (*closing, ClickTray(slot, click))


def _settled(
    model: BarModel, outcome: island_menu.Outcome
) -> tuple[BarModel, tuple[Effect, ...]]:
    match outcome:
        case Menu() as opened:
            return replace(model, opened=opened), (Render(),)
        case Chosen(choice=choice):
            model, closing = _closed(model, restore=restores_focus(choice))
            model, ran = _ran(model, choice)
            return model, (*closing, *ran)
        case Applied(choice=choice):
            model, ran = _ran(model, choice)
            return model, (*ran, Render())
        case _ if outcome is DISMISSED:
            return _closed(model, restore=True)
        case _:
            assert_never(outcome)


def _pressed(
    model: BarModel, action: Action
) -> tuple[BarModel, tuple[Effect, ...]]:
    match action:
        case Action.OPEN_MENU:
            return _opened(model, Panel.WORKSPACE)
        case Action.CLOSE_MENU:
            return _closed(model, restore=True)
        case Action.STOP_DICTATION:
            return model, (UseTool(Tool.DICTATE_TOGGLE),)
        case Action.STOP_RECORDING:
            return _ran(model, Command.STOP_RECORDING)
        case _:
            assert_never(action)


def _opened(
    model: BarModel, panel: Panel, anchor: int | None = None
) -> tuple[BarModel, tuple[Effect, ...]]:
    if model.closed:
        return model, ()
    opening = replace(menu(model, panel), anchor=anchor)
    return model, (
        Expand(opening, remember=model.opened is None),
        Survey(
            listing=panel is Panel.NETWORK,
            ranking=panel in (Panel.PROCESSOR, Panel.MEMORY),
        ),
    )


def _panel(
    model: BarModel, panel: Panel, slot: int | None
) -> tuple[BarModel, tuple[Effect, ...]]:
    if (opened := model.opened) and opened.panel is panel:
        return _closed(model, restore=True)
    return _opened(model, panel, slot)


def _shown(model: BarModel, change: ActivityChange) -> BarModel:
    match change:
        case OverlayShown(enabled):
            return replace(model, overlay_enabled=enabled)
        case DictationShown(active):
            return replace(model, dictating=active)
        case JobShown(job):
            return replace(model, job=job)
        case RecordingShown(recording):
            return replace(model, recording=recording)
        case LayoutShown(enabled):
            return replace(model, layout_enabled=enabled)
        case _:
            assert_never(change)


def _changed(
    before: BarModel, after: BarModel
) -> tuple[BarModel, tuple[Effect, ...]]:
    return after, ((Render(),) if after != before else ())


def _folded(
    model: BarModel, event: Event
) -> tuple[BarModel, tuple[Effect, ...]]:
    match event:
        case Pressed(action):
            return _pressed(model, action)
        case PanelPressed(panel, slot):
            return _panel(model, panel, slot)
        case Paged(months):
            return _changed(model, _paged(model, months))
        case Hovered(key):
            return _changed(model, replace(model, hovered=key))
        case Selected(index):
            if model.opened is None:
                return model, ()
            return _changed(
                model,
                replace(model, opened=replace(model.opened, selected=index)),
            )
        case Picked(index):
            if model.opened is None:
                return model, ()
            return _settled(
                model,
                island_menu.choose(
                    model.opened, model.opened.cells[index].entry
                ),
            )
        case MenuKey(press):
            if model.opened is None:
                return model, ()
            return _settled(model, island_menu.press(model.opened, press))
        case Deactivated():
            return _closed(model, restore=False)
        case VolumeSet(level):
            return _volume(model, level)
        case TrayClicked(slot, click):
            return _tray(model, slot, click)
        case (
            OverlayShown()
            | DictationShown()
            | JobShown()
            | RecordingShown()
            | LayoutShown()
        ):
            return _changed(model, _shown(model, event))
        case ChordHeld(held):
            return replace(model, chord_held=held), (ShowHints(),)
        case Opening(opened, target):
            return replace(
                model,
                opened=opened,
                menu_target=target if target is not None else model.menu_target,
            ), (Render(),)
        case Ticked(seen, next_power, next_material):
            rendered = (Render(),) if seen != model.seen else ()
            return replace(
                model,
                seen=seen,
                next_power=next_power,
                next_material=next_material,
            ), rendered
        case Retargeted(views, motion, opened):
            return replace(model, views=views, motion=motion, opened=opened), ()
        case Framed(motion, last_frame):
            return replace(model, motion=motion, last_frame=last_frame), ()
        case Sampled(at):
            return replace(model, sampled_at=at), ()
        case Closing():
            return replace(model, closed=True), ()
        case _:
            assert_never(event)


def transition(
    model: BarModel, event: Event
) -> tuple[BarModel, Iterator[Effect]]:
    model, effects = _folded(model, event)
    return model, iter(effects)


def spinning(model: BarModel) -> bool:
    return any(
        part is Marker.DOTS
        for view in model.views
        for slot in view.slots
        for part in slot
    )


@dataclass(frozen=True, slots=True)
class Frame:
    motion: IslandMotion
    pulse: float
    """How far through its cycle a quick job's pulse is, from 0 (at rest) to 1."""
    wave_progress: float
    """How far the dictation wave has moved from its last sample to the next, 0 to 1."""
    indicators: bool
    """An activity indicator or the wave is showing, so their capsules repaint."""
    running: bool
    """Something is still moving: the frame loop keeps going."""


def next_frame(model: BarModel, now: float, *, animate: bool) -> Frame:
    elapsed = now - (model.last_frame if model.last_frame is not None else now)
    motion = advance(model.motion, elapsed) if animate else finish(model.motion)
    working = spinning(replace(model, motion=motion))
    spins = animate and working
    waving = animate and model.dictating and model.opened is None
    timing = model.spec.timing
    wave = (
        min(1.0, max(0.0, (now - model.sampled_at) / timing.wave_sample))
        if waving and model.sampled_at is not None
        else 1.0
    )
    return Frame(
        motion,
        now / timing.pulse % 1 if spins else 0.0,
        wave,
        indicators=working or waving,
        running=not settled(motion) or spins or waving,
    )
