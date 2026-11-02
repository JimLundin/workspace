"""Running applications grouped by executable, with stable ordering and window cycling."""

from collections.abc import Sequence
from dataclasses import dataclass

from winapi.icon_pixels import Pixels
from winapi.shapes import Window


@dataclass(frozen=True, slots=True)
class Application:
    identity: str
    windows: tuple[Window, ...]
    image: Pixels | None = None


def applications(observed: Sequence[Window], previous: tuple[Application, ...]) -> tuple[Application, ...]:
    identities = tuple(dict.fromkeys((window.exe or str(window.handle) for window in observed), 0))
    order = tuple(app.identity for app in previous if app.identity in identities)
    order = (*order, *(identity for identity in identities if identity not in order))

    def grouped(identity: str) -> Application:
        current = frozendict((window.handle, window) for window in observed if (window.exe or str(window.handle)) == identity)
        before = next((app for app in previous if app.identity == identity), None)
        retained = tuple(window.handle for window in before.windows if window.handle in current) if before is not None else ()
        handles = (*retained, *(handle for handle in current if handle not in retained))
        return Application(identity, tuple(current[handle] for handle in handles), before.image if before is not None else None)

    return tuple(grouped(identity) for identity in order)


def next_window(app: Application, foreground: int) -> int:
    handles = tuple(window.handle for window in app.windows)
    return handles[(handles.index(foreground) + 1) % len(handles)] if foreground in handles else handles[0]
