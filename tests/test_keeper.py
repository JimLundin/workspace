"""The keeper: runs Workspace, installs changes, and undoes the ones that fail.
Its logic runs on fake processes and a fake clock; its file handling on real folders."""

from collections.abc import Callable
from pathlib import Path

from keeper import (
    PROTECTED,
    Keeper,
    Recovery,
    Stage,
    install,
    prepare_candidate,
    restore,
    snapshot,
    source_files,
)
from keeper_control import STATUS, Control, Install, Keep, Pause, Paused, Refused, Restart, Resume, Resumed, Rollback, Undo, ask, submit, take

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


class World:
    """What the keeper did, and knobs for what happens to it."""

    __slots__ = ("check", "children", "log", "ready", "versions")

    def __init__(self) -> None:
        self.log: list[str] = []
        self.children: dict[str, FakeChild] = {}
        self.ready: set[str] = set()
        self.check = FakeCheck()
        self.versions = 0

    def start(self, name: str) -> FakeChild:
        self.log.append(f"start {name}")
        self.ready.discard(name)
        child = FakeChild(lambda: self.log.append(f"stop {name}"))
        self.children[name] = child
        return child

    def is_ready(self, name: str) -> bool:
        return name in self.ready

    def start_check(self) -> FakeCheck:
        self.log.append("check")
        self.check = FakeCheck()
        return self.check

    def snapshot(self) -> str:
        self.versions += 1
        self.log.append(f"snapshot v{self.versions}")
        return f"v{self.versions}"

    def restore(self, version: str) -> None:
        self.log.append(f"restore {version}")

    def install(self) -> None:
        self.log.append("install")

    def notify(self, text: str) -> None:
        self.log.append(f"notify {text.splitlines()[0]}")

    def show_trial(self, summary: str | None) -> None:
        self.log.append(f"trial {summary}" if summary else "trial over")

    def come_up(self) -> None:
        self.ready |= {"layout", "assistant", "automation"}

    def take(self) -> list[str]:
        log, self.log = self.log, []
        return log


def running(world: World) -> Keeper:
    """A keeper with all supervised programs up."""
    keeper = Keeper(world)
    keeper.start(now=0)
    world.come_up()
    keeper.tick(now=1)
    world.take()
    return keeper


def installed(world: World, keeper: Keeper) -> None:
    """An install that passes its checks and comes up: now on trial."""
    keeper.request(Install("a new snippet"), now=10)
    world.check.outcome = (True, "ok")
    keeper.tick(now=20)
    world.come_up()
    keeper.tick(now=21)


# ---- starting and running --------------------------------------------------------------


def test_starts_layout_assistant_and_automation() -> None:
    world = World()
    keeper = Keeper(world)
    keeper.start(now=0)
    world.come_up()
    keeper.tick(now=1)
    assert world.take() == ["start layout", "start assistant", "start automation"]
    assert keeper.stage is Stage.RUNNING


def test_startup_waits_for_automation_after_layout_and_assistant_are_ready() -> None:
    world = World()
    keeper = Keeper(world)
    keeper.start(now=0)
    world.ready |= {"layout", "assistant"}
    keeper.tick(now=1)
    before_worker_ready = keeper.stage
    world.ready.add("automation")
    keeper.tick(now=2)
    assert (before_worker_ready, keeper.stage) == (Stage.STARTING, Stage.RUNNING)
    assert world.take() == ["start layout", "start assistant", "start automation"]


def test_a_crash_is_restarted() -> None:
    world = World()
    keeper = running(world)
    world.children["layout"].code = 1
    keeper.tick(now=5)
    assert world.take() == ["start layout"]


def test_automation_exit_restarts_only_the_worker_even_when_exit_code_is_zero() -> None:
    for code in (0, 1):
        world = World()
        keeper = running(world)
        layout, assistant, automation = (world.children[name] for name in ("layout", "assistant", "automation"))
        automation.code = code
        keeper.tick(now=5)
        assert world.take() == ["start automation"]
        assert world.children["automation"] is not automation
        assert world.children["layout"] is layout and not layout.stopped
        assert world.children["assistant"] is assistant and not assistant.stopped
        assert not keeper.done
        keeper.tick(now=6)
        assert world.take() == []


def test_layout_restart_preserves_the_worker_and_assistant() -> None:
    world = World()
    keeper = running(world)
    automation, assistant = world.children["automation"], world.children["assistant"]
    keeper.request(Restart("layout"), now=5)
    assert world.take() == ["stop layout", "start layout"]
    assert world.children["automation"] is automation and not automation.stopped
    assert world.children["assistant"] is assistant and not assistant.stopped


def test_independent_restart_preserves_other_children_and_waits_for_fresh_readiness() -> None:
    # Detect treating an intentional assistant restart as Quit Workspace, or
    # accepting its old readiness marker before the replacement is ready.
    for name in ("assistant", "automation"):
        world = World()
        keeper = running(world)
        original = tuple(world.children.items())
        keeper.request(Restart(name), now=5)
        assert world.take() == ["stop " + name, "start " + name]
        for other, child in original:
            if other != name:
                assert world.children[other] is child and not child.stopped
        keeper.tick(now=6)
        waiting = keeper.stage
        assert waiting is Stage.STARTING and not keeper.done
        world.ready.add(name)
        keeper.tick(now=7)
        assert keeper.stage is Stage.RUNNING


def test_deployment_pause_requires_matching_resume_and_keeps_keyboard_alive(tmp_path: Path) -> None:
    # Detect supervision restarting paused children during source replacement,
    # a second sender stealing the pause, or resume replacing retained children.
    world = World()
    keeper = running(world)
    layout, automation = world.children["layout"], world.children["automation"]
    control = Control(tmp_path)
    submit(tmp_path, Pause("deployment", ("assistant",)))
    control.poll(keeper, 5)
    assert STATUS.validate_json((tmp_path / "component-status.json").read_bytes(), strict=True) == Paused("deployment", ("assistant",))
    keeper.tick(now=6)
    keeper.request(Restart("layout"), now=7)
    paused_stage = keeper.stage
    assert paused_stage is Stage.PAUSED and not layout.stopped
    submit(tmp_path, Resume("different-deployment"))
    control.poll(keeper, 8)
    assert isinstance(STATUS.validate_json((tmp_path / "component-status.json").read_bytes(), strict=True), Refused)
    assert "assistant" not in keeper.children
    submit(tmp_path, Resume("deployment"))
    control.poll(keeper, 9)
    assert STATUS.validate_json((tmp_path / "component-status.json").read_bytes(), strict=True) == Resumed("deployment")
    assert keeper.children["layout"] is layout and keeper.children["automation"] is automation
    assert not layout.stopped and not automation.stopped and not keeper.done
    assert keeper.stage is Stage.STARTING


def test_pause_refuses_update_and_duplicate_selections_and_allows_no_restart() -> None:
    world = World()
    keeper = running(world)
    assert not keeper.suspend(("assistant", "assistant"))
    keeper.request(Install(""), now=5)
    assert not keeper.suspend(("assistant",))
    other = World()
    paused = running(other)
    assert paused.suspend(())
    paused.tick(now=6)
    assert other.take() == [] and paused.stage is Stage.PAUSED
    paused.resume(now=7)
    assert other.take() == [] and set(paused.children) == {"layout", "assistant", "automation"}


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
    assert world.take() == ["stop automation", "stop layout"]
    assert world.children["layout"].stopped
    assert world.children["automation"].stopped
    assert keeper.done


def test_shutdown_stops_automation_before_its_ui_and_input_dependencies() -> None:
    world = World()
    keeper = running(world)
    keeper.stop_all()
    assert world.take() == ["stop automation", "stop assistant", "stop layout"]
    keeper.stop_all()
    assert world.take() == []


def test_crashing_over_and_over_without_an_update_gives_up_with_a_notice() -> None:
    world = World()
    keeper = running(world)
    for t in range(4):
        world.children["layout"].code = 1
        keeper.tick(now=10 + t)
    assert world.take()[-1] == "notify The layout keeps crashing, so it's stopped. See layout.log."


def test_repeated_zero_exits_exhaust_the_automation_restart_budget() -> None:
    world = World()
    keeper = running(world)
    for at in (10, 11, 12, 13):
        world.children["automation"].code = 0
        keeper.tick(now=at)
    assert world.take() == [
        "start automation",
        "start automation",
        "start automation",
        "notify The automation keeps crashing, so it's stopped. See automation.log.",
    ]
    assert not world.children["layout"].stopped
    assert not world.children["assistant"].stopped
    assert not keeper.done


# ---- installing ------------------------------------------------------------------------


def test_an_install_is_checked_snapshotted_installed_and_tried() -> None:
    world = World()
    keeper = running(world)
    installed(world, keeper)
    assert world.take() == [
        "check",
        "snapshot v1",
        "stop automation",
        "stop assistant",
        "stop layout",
        "install",
        "start layout",
        "start assistant",
        "start automation",
        "trial a new snippet",
    ]
    assert keeper.stage is Stage.TRIAL


def test_a_change_that_fails_its_checks_is_not_installed() -> None:
    world = World()
    keeper = running(world)
    keeper.request(Install("broken"), now=10)
    world.check.outcome = (False, "FAILED tests.test_engine.test_plain_letters")
    keeper.tick(now=20)
    assert world.take() == ["check", "notify Not installed: the change failed its checks."]
    assert not world.children["layout"].stopped
    assert keeper.stage is Stage.RUNNING


def test_a_change_that_doesnt_come_up_is_undone() -> None:
    world = World()
    keeper = running(world)
    keeper.request(Install("slow"), now=10)
    world.check.outcome = (True, "ok")
    keeper.tick(now=20)
    world.take()
    keeper.tick(now=20 + 31)  # never ready
    assert world.take() == [
        "stop automation",
        "stop assistant",
        "stop layout",
        "restore v1",
        "start layout",
        "start assistant",
        "start automation",
        "notify Update undone: it didn't start.",
    ]


def test_update_is_undone_when_only_automation_never_becomes_ready() -> None:
    world = World()
    keeper = running(world)
    keeper.request(Install("missing worker readiness"), now=10)
    world.check.outcome = (True, "ok")
    keeper.tick(now=20)
    world.take()
    world.ready |= {"layout", "assistant"}
    keeper.tick(now=21)
    assert keeper.stage is Stage.STARTING
    keeper.tick(now=51)
    assert world.take() == [
        "stop automation",
        "stop assistant",
        "stop layout",
        "restore v1",
        "start layout",
        "start assistant",
        "start automation",
        "notify Update undone: it didn't start.",
    ]


def test_update_is_undone_when_automation_exits_before_readiness() -> None:
    world = World()
    keeper = running(world)
    keeper.request(Install("worker exits early"), now=10)
    world.check.outcome = (True, "ok")
    keeper.tick(now=20)
    world.take()
    world.come_up()
    world.children["automation"].code = 0
    keeper.tick(now=21)
    assert world.take() == [
        "stop assistant",
        "stop layout",
        "restore v1",
        "start layout",
        "start assistant",
        "start automation",
        "notify Update undone: it didn't start.",
    ]


def test_a_change_that_exits_while_starting_is_undone_at_once() -> None:
    world = World()
    keeper = running(world)
    keeper.request(Install("crashy"), now=10)
    world.check.outcome = (True, "ok")
    keeper.tick(now=20)
    world.take()
    world.children["assistant"].code = 1
    keeper.tick(now=21)
    assert world.take() == [
        "stop automation",
        "stop layout",
        "restore v1",
        "start layout",
        "start assistant",
        "start automation",
        "notify Update undone: it didn't start.",
    ]


def test_a_crash_during_the_trial_undoes_the_change() -> None:
    world = World()
    keeper = running(world)
    installed(world, keeper)
    world.take()
    world.children["layout"].code = 1
    keeper.tick(now=100)
    assert world.take() == [
        "stop automation",
        "stop assistant",
        "restore v1",
        "start layout",
        "start assistant",
        "start automation",
        "notify Update undone: it crashed during its trial.",
        "trial over",
    ]


def test_automation_exit_during_trial_undoes_the_update_even_when_exit_code_is_zero() -> None:
    for code in (0, 1):
        world = World()
        keeper = running(world)
        installed(world, keeper)
        world.take()
        world.children["automation"].code = code
        keeper.tick(now=100)
        assert world.take() == [
            "stop assistant",
            "stop layout",
            "restore v1",
            "start layout",
            "start assistant",
            "start automation",
            "notify Update undone: it crashed during its trial.",
            "trial over",
        ]


def test_quitting_the_layout_during_the_trial_isnt_a_crash() -> None:
    world = World()
    keeper = running(world)
    installed(world, keeper)
    world.take()
    world.children["layout"].code = 0  # the escape key held
    keeper.tick(now=100)
    assert world.take() == []
    assert keeper.stage is Stage.TRIAL


def test_the_trial_ends_after_ten_minutes_and_the_change_stays() -> None:
    world = World()
    keeper = running(world)
    installed(world, keeper)
    world.take()
    keeper.tick(now=21 + 601)
    assert world.take() == ["trial over"]
    assert keeper.stage is Stage.RUNNING


def test_keep_ends_the_trial_and_undo_rolls_back() -> None:
    world = World()
    keeper = running(world)
    installed(world, keeper)
    keeper.request(Keep(), now=30)
    assert keeper.stage is Stage.RUNNING
    world.take()
    keeper.request(Undo(), now=40)  # undo works after the trial too
    assert world.take() == [
        "stop automation",
        "stop assistant",
        "stop layout",
        "restore v1",
        "start layout",
        "start assistant",
        "start automation",
        "notify Update undone: you undid it.",
    ]


def test_crashing_over_and_over_after_an_update_undoes_it() -> None:
    world = World()
    keeper = running(world)
    installed(world, keeper)
    keeper.request(Keep(), now=30)
    world.take()
    for t in range(4):
        world.children["assistant"].code = 1
        keeper.tick(now=40 + t)
    assert "restore v1" in world.take()


def test_one_thing_at_a_time() -> None:
    world = World()
    keeper = running(world)
    keeper.request(Install("first"), now=10)
    keeper.request(Install("second"), now=11)
    assert world.take() == ["check", "notify Busy installing; try again in a moment."]


# ---- files -----------------------------------------------------------------------------


def write(root: Path, files: dict[str, str]) -> None:
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding="utf-8")


def test_source_files_leave_out_caches_and_history(tmp_path: Path) -> None:
    write(
        tmp_path,
        {
            "a.py": "",
            "pkg/b.py": "",
            "pkg/__pycache__/b.pyc": "",
            ".git/HEAD": "",
            "README.md": "",
            ".mypy_cache/x": "",
            ".runtime/dependency.py": "",
            ".python/Lib/asyncio/__init__.py": "",
        },
    )
    assert source_files(tmp_path) == ["README.md", "a.py", "pkg/b.py"]


def test_snapshot_restore_and_install(tmp_path: Path) -> None:
    live, versions, workspace = tmp_path / "live", tmp_path / "versions", tmp_path / "workspace"
    write(
        live,
        {
            "config.py": "OLD",
            "gone.py": "x",
            "keeper.py": "KEEPER",
            ".runtime/dependency.pyd": "SDK",
        },
    )
    version = snapshot(live, versions)
    write(workspace, {"config.py": "NEW", "added.py": "y", "keeper.py": "HACKED"})
    install(workspace, live)
    assert (live / "config.py").read_text() == "NEW"
    assert (live / "added.py").exists()
    assert not (live / "gone.py").exists()
    assert (live / "keeper.py").read_text() == "KEEPER"  # protected: never replaced
    assert (live / ".runtime/dependency.pyd").read_text() == "SDK"
    restore(versions / version, live)
    assert (live / "config.py").read_text() == "OLD"
    assert (live / "gone.py").exists()
    assert not (live / "added.py").exists()


def test_snapshots_keep_the_last_twenty(tmp_path: Path) -> None:
    live, versions = tmp_path / "live", tmp_path / "versions"
    write(live, {"a.py": ""})
    for _ in range(25):
        snapshot(live, versions)
    assert len(list(versions.iterdir())) == 20


def test_inbox_requests_reach_the_keeper_once_and_in_order(tmp_path: Path) -> None:
    # Detect reordering the inbox, delivering a request twice, or a restart
    # slipping in while the install it followed is being checked.
    world = World()
    keeper = running(world)
    ask(tmp_path, Install("first"))
    ask(tmp_path, Restart("layout"))
    for request in take(tmp_path):
        keeper.request(request, now=5)
    assert world.take() == ["check", "notify Workspace is starting or updating; try the restart again in a moment."]
    assert keeper.stage is Stage.CHECKING and keeper.summary == "first"
    assert tuple(take(tmp_path)) == ()


def test_a_misspelled_request_is_refused_visibly(tmp_path: Path) -> None:
    # Detect an unknown request or component being silently ignored, acted
    # on, or left in the inbox where it blocks source deployment.
    world = World()
    keeper = running(world)
    (tmp_path / "00000000000000000001.json").write_bytes(b'{"action": "undoo"}')
    (tmp_path / "00000000000000000002.json").write_bytes(b'{"action": "restart", "component": "layuot"}')
    for request in take(tmp_path):
        keeper.request(request, now=5)
    assert world.take() == [
        "notify Refused a request the keeper doesn't recognise (00000000000000000001.json).",
        "notify Refused a request the keeper doesn't recognise (00000000000000000002.json).",
    ]
    assert keeper.stage is Stage.RUNNING and not any(tmp_path.iterdir())


def test_the_keeper_and_its_checker_are_protected() -> None:
    assert {"keeper.py", "selfcheck.py", "workspace.pyw"} <= PROTECTED


def test_install_failure_restores_and_restarts() -> None:
    class FailingWorld(World):
        __slots__ = ()

        def install(self) -> None:
            raise PermissionError("locked file")

    world = FailingWorld()
    keeper = running(world)
    keeper.request(Install("change"), now=10)
    world.check.outcome = (True, "ok")
    keeper.tick(20)
    assert "restore v1" in world.log
    assert set(keeper.children) == {"layout", "assistant", "automation"}


def test_undo_survives_keeper_restart(tmp_path: Path) -> None:
    recovery = Recovery(tmp_path / "recovery.json")
    world = World()
    keeper = Keeper(world, recovery)
    keeper.start(0)
    world.come_up()
    keeper.tick(1)
    installed(world, keeper)
    keeper.request(Keep(), now=30)
    restarted = Keeper(world, recovery)
    restarted.recover()
    restarted.request(Undo(), now=40)
    assert "restore v1" in world.log


def test_interrupted_trial_is_restored_before_starting(tmp_path: Path) -> None:
    recovery = Recovery(tmp_path / "recovery.json")
    recovery.write(Rollback(version="v1", pending=True))
    world = World()
    keeper = Keeper(world, recovery)
    keeper.recover()
    keeper.start(0)
    assert world.log[0] == "restore v1"
    assert recovery.read() == Rollback(version=None, pending=False)


def test_recovery_failure_preserves_retry_state(tmp_path: Path) -> None:
    class FailingRestore(World):
        __slots__ = ()

        def restore(self, version: str) -> None:
            raise PermissionError("locked backup")

    recovery = Recovery(tmp_path / "recovery.json")
    recovery.write(Rollback(version="v1", pending=True))
    keeper = Keeper(FailingRestore(), recovery)
    keeper.undoable = "v1"
    keeper.rollback("failed", 0)
    assert keeper.done
    assert recovery.read() == Rollback(version="v1", pending=True)


def test_completed_trial_persists_undo_target(tmp_path: Path) -> None:
    recovery = Recovery(tmp_path / "recovery.json")
    world = World()
    keeper = Keeper(world, recovery)
    keeper.start(0)
    world.come_up()
    keeper.tick(1)
    installed(world, keeper)
    keeper.tick(700)
    assert recovery.read() == Rollback(version="v1", pending=False)


def test_candidate_review_does_not_execute_code_and_is_frozen(tmp_path: Path) -> None:
    live, workspace, candidate = (tmp_path / name for name in ("live", "workspace", "candidate"))
    marker = tmp_path / "executed"
    protected = dict.fromkeys(PROTECTED, "# protected\n")
    write(live, {**protected, "config.py": "OLD"})
    write(workspace, {**protected, "candidate.py": f"from pathlib import Path\nPath({str(marker)!r}).touch()\n"})
    assert not prepare_candidate(workspace, live, candidate, lambda _: False)
    assert not marker.exists()
    write(workspace, {"candidate.py": "NEW"})
    assert "Path(" in (candidate / "candidate.py").read_text(encoding="utf-8")


def test_candidate_is_prepared_without_review_by_default(tmp_path: Path) -> None:
    live, workspace, candidate = (tmp_path / name for name in ("live", "workspace", "candidate"))
    protected = dict.fromkeys(PROTECTED, "# protected\n")
    write(live, {**protected, "config.py": "OLD"})
    write(workspace, {**protected, "config.py": "NEW"})
    assert prepare_candidate(workspace, live, candidate)
    assert (candidate / "config.py").read_text(encoding="utf-8") == "NEW"
    assert (live / "config.py").read_text(encoding="utf-8") == "OLD"


def test_changed_candidate_during_review_is_refused(tmp_path: Path) -> None:
    live, workspace, candidate = (tmp_path / name for name in ("live", "workspace", "candidate"))
    protected = dict.fromkeys(PROTECTED, "# protected\n")
    write(live, protected)
    write(workspace, protected)

    def mutate(root: Path) -> bool:
        write(root, {"new.py": "X = 1"})
        return True

    try:
        prepare_candidate(workspace, live, candidate, mutate)
    except OSError:
        pass
    else:
        raise AssertionError("changed source must be reviewed again")


def test_failed_second_update_keeps_first_update_undoable_after_restart(tmp_path: Path) -> None:
    recovery = Recovery(tmp_path / "recovery.json")
    world = World()
    keeper = Keeper(world, recovery)
    keeper.start(0)
    world.come_up()
    keeper.tick(1)
    installed(world, keeper)
    keeper.request(Install("broken second update"), now=30)
    world.check.outcome = (False, "broken")
    keeper.tick(31)
    assert recovery.read() == Rollback(version="v1", pending=False)
