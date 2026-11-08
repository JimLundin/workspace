"""The assistant's real owners in a test's process, joined to a desktop `Ui` through the wire codec.

`LocalAssistant` is a concrete adapter, not a mock: a real canvas document
(`WorkCanvas` on a temporary SQLite file), a real agent session (`AgentWindow`)
whose view publishes to the desktop, and the assistant's own `DesktopCommands`
carrying out every command the `Ui` sends. Each message crosses `contracts.desktop_link`'s
encoding both ways, as it would between the processes. What the session or
commands hand to owners this fixture doesn't run (work commands, speech for the
conversation, problems) is kept for the test to read.
"""

from collections import deque
from collections.abc import Callable
from pathlib import Path

from assistant.agent_window import AgentWindow
from assistant.desktop_commands import DesktopCommands
from assistant.desktop_port import SessionView
from assistant.work_canvas import WorkCanvas
from contracts.canvas_activity import CanvasRun
from contracts.desktop_link import CanvasChanged, ToAssistant, ToDesktop, from_assistant, from_desktop, to_assistant, to_desktop
from contracts.recording_state import RecordingAction
from contracts.work_canvas_contracts import CanvasPublication
from contracts.work_commands import WorkViewCommand
from desktop_ui.ui import Ui
from protocol import Tool
from tests.test_work_canvas import queue_nothing
from winapi.system_notices import Observed


class LocalDesktop:
    """The `DesktopPort` to a Ui in this process: every message decoded from its own encoding."""

    __slots__ = ("ui",)

    def __init__(self) -> None:
        self.ui: Ui | None = None

    def send(self, message: ToDesktop) -> None:
        if self.ui is not None:
            self.ui.show(from_assistant(to_desktop(message)))

    @property
    def connected(self) -> bool:
        return self.ui is not None


class LocalAssistant:
    __slots__ = (
        "canvas",
        "commands",
        "desktop",
        "jobs",
        "noticed",
        "observed",
        "problems",
        "recorded",
        "session",
        "spoken",
        "tools",
        "work_commands",
    )

    def __init__(self, folder: Path, *, queue: Callable[[CanvasRun], None] = queue_nothing) -> None:
        self.desktop = LocalDesktop()
        self.jobs: deque[Callable[[], None]] = deque()
        """The session view's jobs: the assistant runs them on their own thread; tests `drain` them."""
        self.work_commands: tuple[WorkViewCommand, ...] = ()
        self.spoken: tuple[str, ...] = ()
        self.problems: tuple[str, ...] = ()
        self.tools: tuple[Tool, ...] = ()
        self.recorded: tuple[RecordingAction, ...] = ()
        self.observed: tuple[Observed, ...] = ()
        self.noticed: tuple[tuple[str, str], ...] = ()
        self.canvas = WorkCanvas(folder / "canvas.sqlite3", queue, self.published, autonomous=False)
        self.session: AgentWindow | None = None
        self.commands = DesktopCommands(self.canvas, self.desktop, self)

    def attach(self, ui: Ui) -> AgentWindow:
        """Connect the desktop and open the agent session."""
        self.connect(ui)
        return self.open_session()

    def connect(self, ui: Ui) -> None:
        """Connect the desktop; the agent session opens later (`open_session`), as when a task first needs it."""
        self.desktop.ui = ui
        self.desktop.send(CanvasChanged(self.canvas.publication()))

    def open_session(self) -> AgentWindow:
        if self.session is None:
            self.session = AgentWindow.open(
                lambda: None,
                post=self.jobs.append,
                create_view=lambda _: SessionView(self.desktop, self.canvas.observe_session),
                on_problem=self.problem,
                log=lambda _text: None,
            )
            self.session.canvas_attention(self.canvas.publication().attention)
        return self.session

    def drain(self) -> bool:
        """Run the session view's waiting jobs; whether there were any."""
        ran = bool(self.jobs)
        while self.jobs:
            self.jobs.popleft()()
        return ran

    def published(self, publication: CanvasPublication) -> None:
        if self.session is not None:
            self.session.canvas_attention(publication.attention)
        self.desktop.send(CanvasChanged(publication))

    # ---- the desktop's port ------------------------------------------------------------

    def send(self, command: ToAssistant) -> bool:
        self.commands.handle(from_desktop(to_assistant(command)), self.session)
        return True

    # ---- `DesktopCommands.Controls` ----------------------------------------------------

    def use_tool(self, tool: Tool) -> None:
        self.tools = (*self.tools, tool)

    def recording_action(self, action: RecordingAction) -> None:
        self.recorded = (*self.recorded, action)

    def work_command(self, command: WorkViewCommand) -> None:
        self.work_commands = (*self.work_commands, command)

    def voice(self, text: str) -> None:
        self.spoken = (*self.spoken, text)

    def notify_canvas(self, title: str, target: str) -> None:
        self.noticed = (*self.noticed, (title, target))
        if self.session is not None:
            self.session.notify_canvas(title, target)

    def notices(self, observed: Observed) -> None:
        self.observed = (*self.observed, observed)

    def refresh(self) -> None:
        pass

    def resume(self, task_id: str) -> None:
        pass

    def notify(self, title: str, text: str) -> None:
        pass

    def problem(self, message: str) -> None:
        self.problems = (*self.problems, message)
