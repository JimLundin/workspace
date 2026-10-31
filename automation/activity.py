"""Short-lived desktop context: recent windows, aged and coalesced in memory.

Both processes share these values: the assistant samples them, and the work
process observes the desktop for its runs and receives invocation context.
"""

from dataclasses import dataclass, field, replace
from typing import Final, Literal, assert_never

from pydantic import TypeAdapter

from winapi.shapes import Window

type ContextState = Literal["active", "workspace", "unavailable", "disabled"]
type Observation = Window | Literal["workspace", "unavailable", "disabled"]


@dataclass(frozen=True, slots=True)
class Activity:
    window: Window
    started: float
    seen: float
    agent_active: bool = field(kw_only=True)

    def view(self) -> ActivityView:
        return ActivityView(
            self.window.handle, self.window.exe[:256], self.window.title[:1000], self.started, self.seen, agent_active=self.agent_active
        )


@dataclass(frozen=True, slots=True)
class ActivityView:
    handle: int
    app: str
    title: str
    started: float
    last_seen: float
    agent_active: bool = field(kw_only=True)


@dataclass(frozen=True, slots=True)
class ContextView:
    captured: float
    desktop_state: ContextState
    work_window: ActivityView | None
    recent_activity: tuple[ActivityView, ...]


_CONTEXT = TypeAdapter(ContextView)


@dataclass(frozen=True, slots=True)
class ContextSnapshot:
    captured: float
    state: ContextState
    recent: tuple[Activity, ...] = ()

    @property
    def window(self) -> Window | None:
        return self.recent[-1].window if self.recent and self.state in ("active", "workspace") else None

    def describe(self, limit: int = 12) -> str:
        view = ContextView(
            self.captured,
            self.state,
            self.recent[-1].view() if self.window is not None else None,
            tuple(entry.view() for entry in self.recent[-max(1, min(limit, 64)) :]),
        )
        return _CONTEXT.dump_json(view).decode("utf-8")


@dataclass(frozen=True, slots=True)
class Policy:
    """History retention and the user's context-collection choice."""

    max_age: float = 1800
    capacity: int = 128
    enabled: bool = field(default=True, kw_only=True)

    def __post_init__(self) -> None:
        if self.capacity < 0:
            raise ValueError("Activity capacity must be nonnegative.")


@dataclass(frozen=True, slots=True)
class Sample:
    """The foreground observation and agent ownership at one sampling instant."""

    observation: Observation
    at: float
    agent_active: bool = field(default=False, kw_only=True)


DEFAULT_POLICY: Final = Policy()


def observed(previous: ContextSnapshot, sample: Sample, policy: Policy = DEFAULT_POLICY) -> ContextSnapshot:
    """Age, coalesce, and cap window history without reading the desktop or clock."""
    observation = sample.observation if policy.enabled else "disabled"
    now, agent_active = sample.at, sample.agent_active
    expired = 0
    while expired < len(previous.recent) and now - previous.recent[expired].seen > policy.max_age:
        expired += 1
    entries = previous.recent[expired:]
    match observation:
        case Window() as window:
            last = entries[-1] if entries else None
            if last is not None and last.window == window and last.agent_active == agent_active:
                entries = (*entries[:-1], replace(last, seen=now))
            else:
                entries = (*entries, Activity(window, now, now, agent_active=agent_active))
            return ContextSnapshot(now, "active", entries[-policy.capacity :] if policy.capacity else ())
        case "workspace" | "unavailable":
            return ContextSnapshot(now, observation, entries[-policy.capacity :] if policy.capacity else ())
        case "disabled":
            return ContextSnapshot(now, "disabled")
        case _:
            assert_never(observation)
