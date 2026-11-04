"""Dark external screens while the session is locked, so the lock screen can't burn into an OLED.

Windows can't change the display topology from a locked session
(SetDisplayConfig returns ERROR_ACCESS_DENIED), so the protected screens are
turned off over DDC/CI instead. Windows keeps driving them: the monitor count
and work areas stay the same and placement doesn't react. Only monitors this
owner turned off are turned back on.
"""

from collections.abc import Callable, Mapping, Sequence

from desktop_ui.window_layout import dark_when_locked
from usage import Detail
from winapi import screen, session
from winapi.monitor_power import Applied, Detached, PhysicalMonitors, Power
from winapi.screen import Monitor


def dark_after(dark: frozenset[Monitor], applied: Mapping[Monitor, Applied]) -> frozenset[Monitor]:
    """The monitors left dark by this owner: those it turned off, until it turns them on again.

    A refused request changes nothing, so a failed restore is tried again."""
    off = frozenset(monitor for monitor, result in applied.items() if result is Power.OFF)
    on = frozenset(monitor for monitor, result in applied.items() if result is Power.ON)
    return (dark | off) - on


def set_power(sources: Sequence[PhysicalMonitors], monitor: Monitor, wanted: Power) -> tuple[Applied, int]:
    """The first source whose handles carry the request, and its index; the last refusal otherwise."""
    result: Applied = Detached()
    for index, source in enumerate(sources):
        result = source.set_power(monitor, wanted)
        if result is wanted:
            return result, index
    return result, len(sources)


class LockedScreens:
    """Owns the darkened screens across lock and unlock, on the thread that receives session messages.

    Each DDC/CI request took about 65 ms on the home 4K screen, so a lock or
    unlock costs one request per protected screen on that thread."""

    __slots__ = ("dark", "enabled", "kept", "record")

    def __init__(self, record: Callable[[str, Mapping[str, Detail]], None]) -> None:
        self.record = record
        self.enabled = True
        self.dark: frozenset[Monitor] = frozenset()
        # Native ownership: handles opened while unlocked, used when opening fails during a lock.
        self.kept = PhysicalMonitors()
        if session.locked():  # Started, or restarted after a crash, behind the lock screen.
            self.lock()

    def message(self, message: int, wparam: int) -> None:
        if message == session.WM_DISPLAYCHANGE:
            self.kept.close()
            self.kept = PhysicalMonitors()
        match session.change(message, wparam):
            case session.Change.LOCKED:
                self.lock()
            case session.Change.UNLOCKED:
                self.unlock()
            case None:
                pass

    def toggle(self) -> None:
        self.enabled = not self.enabled
        self.record("dark_when_locked_toggle", {"enabled": self.enabled})

    def lock(self) -> None:
        if self.enabled:
            self.apply(dark_when_locked(screen.monitors()) - self.dark, Power.OFF)

    def unlock(self) -> None:
        self.apply(self.dark, Power.ON)

    def apply(self, monitors: frozenset[Monitor], wanted: Power) -> None:
        if not monitors:
            return
        fresh = PhysicalMonitors()
        try:
            results = frozendict((monitor, set_power((fresh, self.kept), monitor, wanted)) for monitor in monitors)
        finally:
            fresh.close()
        self.dark = dark_after(self.dark, frozendict((monitor, result) for monitor, (result, _) in results.items()))
        kept = sum(1 for _, source in results.values() if source == 1)
        ok = all(result is wanted for result, _ in results.values())
        self.record("dark_when_locked", {"power": wanted.name.lower(), "screens": len(results), "kept_handles": kept, "ok": ok})

    def close(self) -> None:
        """Workspace leaving while locked turns the screens back on rather than leaving them dark."""
        self.unlock()
        self.kept.close()
