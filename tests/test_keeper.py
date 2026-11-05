"""The keeper: runs Workspace, installs changes, and undoes the ones that fail.
Its logic runs on fake processes and a fake clock; its version store on real Git folders."""

import shutil
import unittest
from collections.abc import Callable
from pathlib import Path

from components import Component
from keeper import (
    PROTECTED,
    Keeper,
    Recovery,
    Stage,
    Versions,
    exclusive,
    install_stopped,
    prepare_candidate,
    source_digest,
    source_files,
)
from keeper_control import (
    Install,
    InstallChecking,
    InstallRefused,
    InstallResult,
    InstallStarted,
    Kept,
    Pending,
    Restart,
    Trial,
    Undo,
    ask,
    take,
)
from restart_plan import Relaunch, RestartChildren, RestartPlan

# ---- a fake world for the keeper's logic -----------------------------------------------


class FakeChild:
    __slots__ = ("code", "on_stop", "stopped")

    def __init__(self, on_stop: Callable[[], None]) -> None:
        self.code: int | None = None
        self.stopped = False
        self.on_stop = on_stop

    def poll(self) -> int | None:
        return self.code

    def stop(self) -> None:
        self.on_stop()
        self.stopped = True
        self.code = 0


class FakeCheck:
    __slots__ = ("outcome",)

    def __init__(self) -> None:
        self.outcome: tuple[bool, str] | None = None

    def result(self) -> tuple[bool, str] | None:
        return self.outcome

    def cancel(self) -> None:
        self.outcome = (False, "cancelled")


EVERYTHING = RestartChildren(("layout", "assistant"))


class World:
    """What the keeper did, and knobs for what happens to it."""

    __slots__ = ("check", "children", "log", "plans", "ready", "results", "versions")

    def __init__(self) -> None:
        self.log: list[str] = []
        self.results: list[InstallResult] = []
        self.children: dict[str, FakeChild] = {}
        self.ready: set[str] = set()
        self.check = FakeCheck()
        self.versions = 0
        self.plans: dict[str | None, RestartPlan] = {}
        """What installing the candidate (None) or restoring a version restarts; every child otherwise."""

    def start(self, name: Component) -> FakeChild:
        self.log.append(f"start {name}")
        self.ready.discard(name)
        child = FakeChild(lambda: self.log.append(f"stop {name}"))
        self.children[name] = child
        return child

    def is_ready(self, name: Component) -> bool:
        return name in self.ready

    def start_check(self, install: Install) -> FakeCheck:
        self.log.append("check" if install.checked is None else f"check after fast check {install.checked}")
        self.check = FakeCheck()
        return self.check

    def plan(self, version: str | None) -> RestartPlan:
        return self.plans.get(version, EVERYTHING)

    def snapshot(self) -> str:
        self.versions += 1
        self.log.append(f"snapshot v{self.versions}")
        return f"v{self.versions}"

    def install(self, summary: str) -> None:
        self.log.append("install")

    def restore(self, version: str) -> None:
        self.log.append(f"restore {version}")

    def relaunch(self) -> None:
        self.log.append("relaunch")

    def notify(self, text: str) -> None:
        self.log.append(f"notify {text.splitlines()[0]}")

    def note(self, text: str) -> None:
        self.log.append(f"note {text.splitlines()[0]}")

    def record(self, result: InstallResult) -> None:
        self.results.append(result)

    def come_up(self) -> None:
        self.ready |= {"layout", "assistant"}

    def take(self) -> list[str]:
        log, self.log = self.log, []
        return log


def running(world: World, recovery: Recovery | None = None) -> Keeper:
    """A keeper with all supervised programs up."""
    keeper = Keeper(world, recovery)
    keeper.start(now=0)
    world.come_up()
    keeper.tick(now=1)
    world.take()
    return keeper


def installed(world: World, keeper: Keeper) -> None:
    """An install that passes its checks and comes up: now on trial."""
    keeper.request(Install("a new snippet", "digest", None), now=10)
    world.check.outcome = (True, "ok")
    keeper.tick(now=20)
    world.come_up()
    keeper.tick(now=21)


# ---- starting and running --------------------------------------------------------------


def test_starts_the_layout_then_the_assistant() -> None:
    world = World()
    keeper = Keeper(world)
    keeper.start(now=0)
    world.come_up()
    keeper.tick(now=1)
    assert world.take() == ["start layout", "start assistant"]
    assert keeper.stage is Stage.RUNNING


def test_a_crash_is_restarted() -> None:
    world = World()
    keeper = running(world)
    world.children["layout"].code = 1
    keeper.tick(now=5)
    assert world.take() == ["start layout"]


def test_independent_restart_preserves_the_other_child_and_waits_for_fresh_readiness() -> None:
    # Detect treating an intentional assistant restart as Quit Workspace, or
    # accepting its old readiness marker before the replacement is ready.
    pairs: tuple[tuple[Component, Component], ...] = (("assistant", "layout"), ("layout", "assistant"))
    for name, other in pairs:
        world = World()
        keeper = running(world)
        kept = world.children[other]
        keeper.request(Restart(name), now=5)
        assert world.take() == ["stop " + name, "start " + name]
        assert world.children[other] is kept and not kept.stopped
        keeper.tick(now=6)
        assert keeper.stage is Stage.STARTING and not keeper.done
        world.ready.add(name)
        keeper.tick(now=7)
        assert keeper.stage is Stage.RUNNING


def test_quitting_the_layout_on_purpose_leaves_it_stopped_until_asked() -> None:
    world = World()
    keeper = running(world)
    world.children["layout"].code = 0  # the escape key held
    keeper.tick(now=5)
    assert world.take() == []
    keeper.request(Restart("layout"), now=6)
    assert world.take() == ["start layout"]


def test_quitting_the_assistant_quits_everything() -> None:
    world = World()
    keeper = running(world)
    world.children["assistant"].code = 0  # Quit in the tray menu
    keeper.tick(now=5)
    assert world.take() == ["stop layout"]
    assert keeper.done


def test_shutdown_stops_the_assistant_before_the_keyboard() -> None:
    world = World()
    keeper = running(world)
    keeper.stop_all()
    assert world.take() == ["stop assistant", "stop layout"]
    keeper.stop_all()
    assert world.take() == []


def test_crashing_over_and_over_without_an_update_gives_up_with_a_notice() -> None:
    world = World()
    keeper = running(world)
    for t in range(4):
        world.children["layout"].code = 1
        keeper.tick(now=10 + t)
    assert world.take()[-1] == "notify The layout keeps crashing, so it's stopped. See layout.log."


# ---- installing ------------------------------------------------------------------------


def test_an_install_restarts_only_what_it_affects_and_reports_once_that_is_up() -> None:
    # Detect restarting the keyboard for an assistant-only change, or reporting
    # the install before the restarted program proved it starts.
    world = World()
    world.plans[None] = RestartChildren(("assistant",))
    keeper = running(world)
    layout = world.children["layout"]
    keeper.request(Install("a new snippet", "digest", None), now=10)
    world.check.outcome = (True, "ok")
    keeper.tick(now=20)
    assert world.take() == ["check", "snapshot v1", "stop assistant", "install", "start assistant"]
    assert world.results == [InstallChecking("digest")]
    world.ready.add("assistant")
    keeper.tick(now=21)
    assert keeper.stage is Stage.TRIAL
    assert world.children["layout"] is layout and not layout.stopped
    assert world.results == [InstallChecking("digest"), InstallStarted("digest", "a new snippet", "v1")]


def test_a_change_no_program_loads_installs_without_a_restart_or_trial(tmp_path: Path) -> None:
    world = World()
    world.plans[None] = RestartChildren(())
    recovery = Recovery(tmp_path / "rollback.json")
    keeper = running(world, recovery)
    keeper.request(Install("docs", "digest", None), now=10)
    world.check.outcome = (True, "ok")
    keeper.tick(now=20)
    assert world.take() == ["check", "snapshot v1", "install"]
    assert keeper.stage is Stage.RUNNING
    assert world.results[-1] == InstallStarted("digest", "docs", "v1")
    assert recovery.read() == Kept("v1")


def test_a_protected_change_relaunches_the_keeper_which_tries_it(tmp_path: Path) -> None:
    # Detect a keeper change installed without relaunching, a relaunched keeper
    # skipping the trial, or a startup failure after the relaunch that isn't undone.
    world = World()
    world.plans[None] = Relaunch.KEEPER
    recovery = Recovery(tmp_path / "rollback.json")
    keeper = running(world, recovery)
    keeper.request(Install("keeper fix", "digest", "digest", "C:/stage"), now=10)
    world.check.outcome = (True, "ok")
    keeper.tick(now=20)
    assert world.take() == ["check after fast check digest", "snapshot v1", "stop assistant", "stop layout", "install", "relaunch"]
    assert keeper.done
    started = InstallStarted("digest", "keeper fix", "v1")
    assert recovery.read() == Trial("v1", started)

    relaunched = World()
    successor = Keeper(relaunched, recovery)
    successor.recover()
    assert recovery.read() == Pending("v1"), "Quitting during the relaunched trial must restore on the next launch."
    successor.start(now=0)
    relaunched.come_up()
    successor.tick(now=1)
    assert successor.stage is Stage.TRIAL and relaunched.results == [started]
    relaunched.take()
    relaunched.children["assistant"].code = 1
    successor.tick(now=5)
    assert "restore v1" in relaunched.take()
    assert relaunched.results[-1] == InstallRefused("digest", "Update undone: it crashed during its trial.")


def test_a_change_that_fails_its_checks_is_not_installed() -> None:
    world = World()
    keeper = running(world)
    keeper.request(Install("broken", "digest", None), now=10)
    world.check.outcome = (False, "FAILED tests.test_engine.test_plain_letters")
    keeper.tick(now=20)
    assert world.take() == ["check", "note Not installed: the change failed its checks."]
    assert not world.children["layout"].stopped
    assert keeper.stage is Stage.RUNNING
    # The requesting task reads why, instead of guessing from the running source.
    assert world.results == [
        InstallChecking("digest"),
        InstallRefused("digest", "Not installed: the change failed its checks.\n\nFAILED tests.test_engine.test_plain_letters"),
    ]


def test_a_change_that_doesnt_come_up_is_undone() -> None:
    world = World()
    keeper = running(world)
    keeper.request(Install("slow", "digest", None), now=10)
    world.check.outcome = (True, "ok")
    keeper.tick(now=20)
    world.take()
    keeper.tick(now=20 + 31)  # never ready
    assert world.take() == [
        "stop assistant",
        "stop layout",
        "restore v1",
        "start layout",
        "start assistant",
        "note Update undone: it didn't start.",
    ]
    assert world.results[-1] == InstallRefused("digest", "Update undone: it didn't start.")


def test_a_crash_during_the_trial_undoes_the_change_and_restarts_what_stopped() -> None:
    world = World()
    keeper = running(world)
    installed(world, keeper)
    world.take()
    world.children["layout"].code = 1
    keeper.tick(now=100)
    assert world.take() == ["stop assistant", "restore v1", "start layout", "start assistant", "note Update undone: it crashed during its trial."]


def test_quitting_the_layout_during_the_trial_isnt_a_crash() -> None:
    world = World()
    keeper = running(world)
    installed(world, keeper)
    world.take()
    world.children["layout"].code = 0  # the escape key held
    keeper.tick(now=100)
    assert world.take() == []
    assert keeper.stage is Stage.TRIAL


def test_the_trial_ends_after_ten_minutes_and_the_change_stays(tmp_path: Path) -> None:
    world = World()
    recovery = Recovery(tmp_path / "rollback.json")
    keeper = running(world, recovery)
    installed(world, keeper)
    world.take()
    assert recovery.read() == Pending("v1")
    keeper.tick(now=21 + 601)
    assert world.take() == []
    assert keeper.stage is Stage.RUNNING
    assert recovery.read() == Kept("v1")


def test_undo_restores_the_replaced_version_with_only_the_programs_it_affects() -> None:
    world = World()
    world.plans["v1"] = RestartChildren(("assistant",))
    keeper = running(world)
    installed(world, keeper)
    keeper.tick(now=21 + 601)
    world.take()
    keeper.request(Undo(), now=640)  # undo works after the trial too
    assert world.take() == ["stop assistant", "restore v1", "start assistant", "note Update undone: you undid it."]
    keeper.request(Undo(), now=650)
    assert world.take() == ["notify There's no update to undo."]


def test_undoing_a_keeper_change_relaunches_the_restored_keeper() -> None:
    world = World()
    world.plans["v1"] = Relaunch.KEEPER
    keeper = running(world)
    installed(world, keeper)
    keeper.tick(now=21 + 601)
    world.take()
    keeper.request(Undo(), now=640)
    assert world.take() == ["stop assistant", "stop layout", "restore v1", "relaunch", "note Update undone: you undid it."]
    assert keeper.done


def test_crashing_over_and_over_after_an_update_undoes_it() -> None:
    world = World()
    keeper = running(world)
    installed(world, keeper)
    keeper.tick(now=21 + 601)
    world.take()
    for t in range(4):
        world.children["assistant"].code = 1
        keeper.tick(now=640 + t)
    assert "restore v1" in world.take()


def test_one_thing_at_a_time() -> None:
    world = World()
    keeper = running(world)
    keeper.request(Install("first", "digest", None), now=10)
    keeper.request(Install("second", "other", None), now=11)
    assert world.take() == ["check", "note Busy installing; try again in a moment."]
    assert world.results[-1] == InstallRefused("other", "Busy installing; try again in a moment.")


def test_install_failure_restores_and_restarts() -> None:
    class FailingWorld(World):
        __slots__ = ()

        def install(self, summary: str) -> None:
            raise PermissionError("locked file")

    world = FailingWorld()
    keeper = running(world)
    keeper.request(Install("change", "digest", None), now=10)
    world.check.outcome = (True, "ok")
    keeper.tick(20)
    assert "restore v1" in world.log
    assert set(keeper.children) == {"layout", "assistant"}


# ---- recovery across keeper restarts ---------------------------------------------------


def test_undo_survives_keeper_restart(tmp_path: Path) -> None:
    recovery = Recovery(tmp_path / "rollback.json")
    world = World()
    keeper = running(world, recovery)
    installed(world, keeper)
    keeper.tick(now=21 + 601)
    world.take()
    restarted = Keeper(world, recovery)
    restarted.recover()
    assert world.take() == []  # a kept change stays installed on the next launch
    restarted.request(Undo(), now=40)
    assert "restore v1" in world.log


def test_interrupted_trial_is_restored_before_starting(tmp_path: Path) -> None:
    recovery = Recovery(tmp_path / "rollback.json")
    recovery.write(Pending("v1"))
    world = World()
    keeper = Keeper(world, recovery)
    keeper.recover()
    keeper.start(0)
    assert world.log[:2] == ["restore v1", "notify Update undone: the previous trial or installation was interrupted."]
    assert recovery.read() == Kept(None)


def test_an_interrupted_keeper_change_relaunches_after_its_restore(tmp_path: Path) -> None:
    # Detect the restoring keeper starting children on keeper code it just replaced.
    recovery = Recovery(tmp_path / "rollback.json")
    recovery.write(Pending("v1"))
    world = World()
    world.plans["v1"] = Relaunch.KEEPER
    keeper = Keeper(world, recovery)
    keeper.recover()
    assert keeper.done and world.take()[-1] == "relaunch"


def test_recovery_failure_preserves_retry_state(tmp_path: Path) -> None:
    class FailingRestore(World):
        __slots__ = ()

        def restore(self, version: str) -> None:
            raise PermissionError("locked backup")

    recovery = Recovery(tmp_path / "rollback.json")
    keeper = Keeper(FailingRestore(), recovery)
    keeper.undoable = "v1"
    keeper.rollback("failed", 0)
    assert keeper.done
    assert recovery.read() == Pending("v1")


def test_failed_second_update_keeps_first_update_undoable_after_restart(tmp_path: Path) -> None:
    recovery = Recovery(tmp_path / "rollback.json")
    world = World()
    keeper = running(world, recovery)
    installed(world, keeper)
    keeper.request(Install("broken second update", "digest", None), now=30)
    world.check.outcome = (False, "broken")
    keeper.tick(31)
    assert recovery.read() == Kept("v1")


# ---- the inbox -------------------------------------------------------------------------


def test_inbox_requests_reach_the_keeper_once_and_in_order(tmp_path: Path) -> None:
    # Detect reordering the inbox, delivering a request twice, or a restart
    # slipping in while the install it followed is being checked.
    world = World()
    keeper = running(world)
    ask(tmp_path, Install("first", "digest", None, "C:/stage"))
    ask(tmp_path, Restart("layout"))
    for request in take(tmp_path):
        keeper.request(request, now=5)
    assert world.take() == ["check", "notify Workspace is starting or updating; try the restart again in a moment."]
    assert keeper.stage is Stage.CHECKING and keeper.summary == "first"
    assert tuple(take(tmp_path)) == ()


def test_a_misspelled_request_is_refused_visibly(tmp_path: Path) -> None:
    # Detect an unknown request or component being silently ignored, acted on,
    # or left in the inbox where it blocks the next install.
    world = World()
    keeper = running(world)
    (tmp_path / "00000000000000000001.json").write_bytes(b'{"action": "undoo"}')
    (tmp_path / "00000000000000000002.json").write_bytes(b'{"action": "restart", "component": "automation"}')
    for request in take(tmp_path):
        keeper.request(request, now=5)
    assert world.take() == [
        "notify Refused a request the keeper doesn't recognise (00000000000000000001.json).",
        "notify Refused a request the keeper doesn't recognise (00000000000000000002.json).",
    ]
    assert keeper.stage is Stage.RUNNING and not any(tmp_path.iterdir())


# ---- files -----------------------------------------------------------------------------


def write(root: Path, files: dict[str, bytes]) -> None:
    for name, data in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_bytes(data)


def test_source_files_leave_out_caches_and_history(tmp_path: Path) -> None:
    write(
        tmp_path,
        {
            "a.py": b"",
            "pkg/b.py": b"",
            "pkg/__pycache__/b.pyc": b"",
            ".git/HEAD": b"",
            "README.md": b"",
            ".mypy_cache/x": b"",
            ".runtime/dependency.py": b"",
            ".python/Lib/asyncio/__init__.py": b"",
        },
    )
    assert source_files(tmp_path) == ["README.md", "a.py", "pkg/b.py"]


def test_the_agent_cannot_change_protected_files_but_a_deploy_can(tmp_path: Path) -> None:
    live, workspace, candidate = (tmp_path / name for name in ("live", "workspace", "candidate"))
    protected = dict.fromkeys(PROTECTED, b"# protected\n")
    write(live, {**protected, "config.py": b"OLD"})
    write(workspace, {**protected, "config.py": b"NEW"})
    prepare_candidate(workspace, live, candidate, deploy=False)
    assert (candidate / "config.py").read_bytes() == b"NEW" and (live / "config.py").read_bytes() == b"OLD"
    write(workspace, {"keeper.py": b"# changed\n"})
    with unittest.TestCase().assertRaisesRegex(OSError, "keeper.py"):
        prepare_candidate(workspace, live, candidate, deploy=False)
    prepare_candidate(workspace, live, candidate, deploy=True)
    assert (candidate / "keeper.py").read_bytes() == b"# changed\n"


def needs_git() -> None:
    if shutil.which("git") is None:
        raise unittest.SkipTest("The keeper's version store uses Git")


def test_versions_install_and_restore_exact_bytes_beside_an_untouched_runtime(tmp_path: Path) -> None:
    # Detect line-ending conversion from the installed copy's own .gitattributes,
    # a restore that keeps an installed file or loses a removed one, a touched
    # runtime, or stale bytecode surviving an install.
    needs_git()
    live, candidate = tmp_path / "live", tmp_path / "candidate"
    write(
        live,
        {
            ".gitattributes": b"* text=auto eol=lf\n",
            ".runtime/dependency.pyd": b"SDK",
            "config.py": b"OLD\r\n",
            "gone.py": b"x",
            "pkg/__pycache__/config.cpython-315.pyc": b"stale",
        },
    )
    before = source_digest(live)
    versions = Versions(tmp_path / "versions.git", live)
    previous = versions.snapshot()
    assert versions.snapshot() == previous, "An unchanged copy is the same version."
    write(candidate, {"config.py": b"NEW\r\n", "added.py": b"y"})
    installed = versions.install(candidate, "A change")
    assert installed != previous and versions.installed() == installed
    assert (live / "config.py").read_bytes() == b"NEW\r\n" and (live / "added.py").exists() and not (live / "gone.py").exists()
    assert not (live / "pkg" / "__pycache__").exists()
    versions.restore(previous)
    assert source_digest(live) == before and versions.installed() == previous
    assert (live / "config.py").read_bytes() == b"OLD\r\n" and not (live / "added.py").exists()
    assert (live / ".runtime/dependency.pyd").read_bytes() == b"SDK"


def test_a_deploy_without_a_keeper_installs_a_version_undo_can_restore(tmp_path: Path) -> None:
    # Detect a stopped-copy deploy that bypasses the version store, or one that
    # overwrites an interrupted install the next keeper must recover first.
    needs_git()
    live, stage, state, repository = tmp_path / "live", tmp_path / "stage", tmp_path / "keeper", tmp_path / "versions.git"
    write(live, {"config.py": b"OLD"})
    write(stage, {"config.py": b"NEW"})
    previous = install_stopped(stage, live, "Deploy", state=state, versions=repository)
    assert (live / "config.py").read_bytes() == b"NEW"
    assert Recovery(state / "rollback.json").read() == Kept(previous)
    Versions(repository, live).restore(previous)
    assert (live / "config.py").read_bytes() == b"OLD"
    Recovery(state / "rollback.json").write(Pending(previous))
    with unittest.TestCase().assertRaisesRegex(OSError, "interrupted update"):
        install_stopped(stage, live, "Deploy", state=state, versions=repository)
    assert (live / "config.py").read_bytes() == b"OLD"


def test_one_holder_of_the_keeper_lock_at_a_time(tmp_path: Path) -> None:
    # Detect a deploy syncing files while a keeper runs, or a second keeper starting.
    with exclusive(tmp_path) as first, exclusive(tmp_path) as second:
        assert first and not second
    with exclusive(tmp_path) as again:
        assert again
