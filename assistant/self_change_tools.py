"""The self-change tool family: the agent edits, checks, publishes and installs Workspace's own source."""

import hashlib
import os
import tempfile
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Final, Protocol

from pydantic import Field, TypeAdapter

from assistant.agent_tools import (
    NO_ARGUMENTS,
    Args,
    ArgumentError,
    Display,
    NoArguments,
    Output,
    Session,
    Tool,
    argument_spec,
    described,
    fixed,
    typed_classification,
    typed_run,
)
from assistant.publishing import DEFAULT_REMOTE, Installed, Landing, PublishError, land_installed, publish_source
from assistant.workspace import CheckCompleted, CheckInterrupted, CheckResult, SourceError, Workspace
from automation.actions import Change, Classification, Observation, Operation, target
from automation.store import TaskStore
from contracts.json_value import Json
from contracts.task import ActionUncertain, ActionVerified, Blocked, Claim, Until, Waiting
from keeper import CHECK_S, START_S, Versions, copy_source, source_digest
from keeper_control import InstallRefused, InstallStarted, install_result

MAX_SOURCE_CHARS: Final = 60_000
"""Most of one source file the model reads at once."""

INSTRUCTIONS: Final = (
    "You can also change Workspace itself, the program you are part of. You work on a copy (your workspace): "
    "read README.md and the Design section of AGENTS.md first, then the files you need. Follow those design rules: "
    "immutable dataclasses, typed variants and pure decisions; preserve the keyboard's allocation and latency profile. "
    "Keep strict types with no Any, __slots__ on classes, small functions and docstrings that say why; "
    "add or update tests for changed behavior. User settings (apps, "
    "snippets, rewrite prompts) live in config.py. A request to improve or fix Workspace authorizes you to edit its "
    "source, prompts, model settings and tests, run checks, install and reload the result. Complete that workflow unless "
    "the user explicitly asks for a draft or advice only. Keep changes focused and preserve unrelated work. "
    "Run check_changes, inspect any failures, fix them and check again; then call apply_changes with a one-line summary. "
    "The keeper tests a frozen copy, installs it, restarts Workspace and undoes failures; once it reports the install, "
    "the task commits the installed source to main and pushes it, so the change is kept in the repository. "
    "Run focused tests with run_powershell while iterating if useful; check_changes is the required gate. "
    "keeper.py, selfcheck.py, runtime.py, workspace.pyw and bundled dependencies are protected; edit through the source tools. "
    "publish_changes is only for a review branch the user asks for; it does not install or merge into main."
)

_INSTALLATION: Final = "apply_changes"
_SOURCE_TREE: Final = target("source-tree", "workspace")


type Text = Annotated[str, Field(strict=True)]


@dataclass(frozen=True, slots=True)
class PathArguments:
    path: Text


@dataclass(frozen=True, slots=True)
class WriteArguments:
    path: Text
    content: Text


@dataclass(frozen=True, slots=True)
class EditArguments:
    path: Text
    old: Text
    new: Text


@dataclass(frozen=True, slots=True)
class SummaryArguments:
    summary: Text


_PATH: Final = TypeAdapter(PathArguments)
_WRITE: Final = TypeAdapter(WriteArguments)
_EDIT: Final = TypeAdapter(EditArguments)
_SUMMARY: Final = TypeAdapter(SummaryArguments)


def _source_file(path: str) -> tuple[str, ...]:
    return ("source", target("source", os.path.normcase(os.path.normpath(path.replace("\\", "/")))))


def _source_change[A: PathArguments | WriteArguments | EditArguments](arguments: TypeAdapter[A]) -> Callable[[Mapping[str, Json]], Classification]:
    return typed_classification(arguments, lambda request: Change(_source_file(request.path)), Change(("source",)))


@dataclass(frozen=True, slots=True)
class InstallOperation:
    """The install apply_changes requests: its summary, the checked digest and the destination."""

    summary: str
    source_digest: Annotated[str, Field(min_length=64, max_length=64)]
    destination: str
    diff_sha256: str


_INSTALL_OPERATION: Final = TypeAdapter(InstallOperation)


def _installation(operation: InstallOperation) -> tuple[str, ...]:
    """The checked digest and destination let a later run verify what the keeper installed."""
    return ("source", target("installed-root", operation.destination), "source-digest:" + operation.source_digest)


@dataclass(frozen=True, slots=True)
class InstalledCopy:
    """The running source, the keeper's folders and where verified installs land in Git."""

    live: Path
    state: Path
    """Where the keeper reports each install."""
    versions: Path
    """The keeper's version repository; the assistant only reads it."""
    landing: Landing | None
    """None leaves installs unmerged: only for configurations without a repository."""


INSTALL_WAIT_S: Final = CHECK_S + START_S + 60
"""How long a requested install may go unreported before the task stops waiting for it."""


def verified_installation(store: TaskStore, claim: Claim, installed: InstalledCopy) -> Waiting | None:
    """Finish a requested installation from the keeper's reported result for its exact digest.

    The keeper's checks and restart take minutes. Comparing the running source once,
    two minutes after the request, blocked installs that were still being checked
    and hid the keeper's reason when it refused one.
    """
    for action in store.unverified_actions(claim.task.id):
        if action.specification.tool != _INSTALLATION:
            continue
        requested = next((name.removeprefix("source-digest:") for name in action.specification.resources if name.startswith("source-digest:")), "")
        now = time.time()
        match install_result(installed.state):
            case InstallRefused(digest=digest, reason=reason) if digest == requested:
                # The request was delivered; what is verified is the keeper's refusal.
                if store.finish_action(action.id, ActionVerified(f"The keeper refused the install. {reason}"[:8_000]), at=now) is None:
                    return Waiting(Blocked("The keeper refused the install, but its result could not be recorded. Resume to inspect it again."))
                # A known rejection is repairable, not an uncertain installation.
                # The durable action evidence reaches the next model turn through
                # WorkExecution.instructions, including after another restart.
                continue
            case InstallStarted(digest=digest, summary=summary, version=version) if digest == requested:
                location = target("installed-root", str(installed.live.absolute()))
                if source_digest(installed.live) != requested or location not in action.specification.resources:
                    return Waiting(Blocked("The keeper reported this install, but the running source differs from it. Inspect the installation."))
                merged = ""
                if installed.landing is not None:
                    # An install that never reaches the repository is lost at the next
                    # deployment. The action stays unverified until it lands; landing
                    # again after a success finds it already merged.
                    try:
                        with tempfile.TemporaryDirectory(prefix="workspace-base-") as base:
                            Versions(installed.versions, installed.live).export(version, Path(base))
                            merged = " " + land_installed(Installed(installed.live, Path(base), summary), installed.landing)
                    except (OSError, PublishError) as error:
                        return Waiting(Blocked(f"The change is installed but was not merged into the repository: {error}"[:8_000]))
                verified = ActionVerified("The keeper installed the checked change; the running source matches its SHA-256 digest." + merged)
                if store.finish_action(action.id, verified, at=now) is None:
                    return Waiting(Blocked("The installed source matched, but verification could not be recorded. Resume to inspect it again."))
            case _ if now < action.started_at + INSTALL_WAIT_S:
                return Waiting(Until(now + 15, "Waiting for the keeper to check and install the change."))
            case _:
                return Waiting(Blocked(f"The keeper reported no result for this install within {INSTALL_WAIT_S / 60:.0f} minutes. See keeper.log."))
    return None


class Installer(Session, Protocol):
    """The session self-change acts through, told when the keeper is asked to install."""

    def installation_requested(self, summary: str, /) -> None:
        """The task is over: its run ends while the keeper installs."""
        ...


@dataclass(frozen=True, slots=True)
class Delivery:
    """Where checked changes go: the keeper's install root, and the branch publishing pushes."""

    install_root: Path | None
    branch: str


@dataclass(frozen=True, slots=True)
class Checked:
    """A draft that passed its affected checks: its diff against the running version
    and the digest of the frozen source those checks ran on."""

    diff: str
    digest: str


class SelfChange:
    """The agent's draft of Workspace and what its checks established.

    Mutable by necessity: the checked diff and a failed check follow the run's
    tool calls. Only this family's handlers write them.
    """

    __slots__ = ("check_failed", "checked", "delivery", "session", "workspace")

    def __init__(self, session: Installer, workspace: Workspace, delivery: Delivery) -> None:
        self.session, self.workspace, self.delivery = session, workspace, delivery
        self.checked: Checked | None = None
        """The draft that last passed its checks."""
        self.check_failed = False

    def tools(self) -> tuple[Tool, ...]:
        return (
            Tool(
                argument_spec("list_source", "List Workspace's own source files (your workspace copy).", NO_ARGUMENTS),
                typed_run(NO_ARGUMENTS, self.list_source),
                fixed(Observation(("source",))),
                Display.PUBLIC,
            ),
            Tool(
                argument_spec("read_source", "Read one of Workspace's source files. Start with README.md and AGENTS.md.", _PATH),
                typed_run(_PATH, self.read_source),
                typed_classification(_PATH, lambda request: Observation(_source_file(request.path)), Observation(("source",))),
                Display.PUBLIC,
            ),
            Tool(
                argument_spec("write_source", "Write a whole source file in your workspace (new or replaced).", _WRITE),
                typed_run(_WRITE, self.write_source),
                _source_change(_WRITE),
                Display.PUBLIC,
            ),
            Tool(
                argument_spec("edit_source", "Replace text that appears exactly once in a source file in your workspace.", _EDIT),
                typed_run(_EDIT, self.edit_source),
                _source_change(_EDIT),
                Display.PUBLIC,
            ),
            Tool(
                argument_spec("delete_source", "Delete a source file in your workspace.", _PATH),
                typed_run(_PATH, self.delete_source),
                _source_change(_PATH),
                Display.PUBLIC,
            ),
            Tool(
                argument_spec("show_changes", "Your changes so far, as a diff against the running workspace.", NO_ARGUMENTS),
                typed_run(NO_ARGUMENTS, self.show_changes),
                fixed(Observation(("source", _SOURCE_TREE))),
                Display.PUBLIC,
            ),
            Tool(
                argument_spec(
                    "check_changes",
                    (
                        "Run the tests this change affects, including Windows integration tests, then Ruff, "
                        "the architecture and interface reviews, and pyright on changed files; "
                        "fix every reported failure."
                    ),
                    NO_ARGUMENTS,
                ),
                typed_run(NO_ARGUMENTS, self.check_changes),
                fixed(Change(("exclusive", _SOURCE_TREE))),
                Display.PUBLIC,
            ),
            Tool(
                argument_spec(
                    "apply_changes",
                    "Submit checked changes to the keeper: it tests a frozen copy and installs if they pass, "
                    "then the change is committed to main and pushed. If they fail to start or crash, they're undone automatically.",
                    _SUMMARY,
                ),
                typed_run(_SUMMARY, self.apply_changes),
                typed_classification(_INSTALL_OPERATION, lambda operation: Change(_installation(operation)), Change(("source",))),
                Display.PUBLIC,
            ),
            Tool(
                argument_spec(
                    "publish_changes",
                    "Test, commit and push requested source changes to a new Git branch; main and running source stay unchanged.",
                    _SUMMARY,
                ),
                typed_run(_SUMMARY, self.publish_changes),
                fixed(Change(("exclusive",))),
                Display.PUBLIC,
            ),
            Tool(
                argument_spec("discard_changes", "Throw away your changes: back to the running version.", NO_ARGUMENTS),
                typed_run(NO_ARGUMENTS, self.discard_changes),
                fixed(Change(("source", _SOURCE_TREE))),
                Display.PUBLIC,
            ),
        )

    def source(self) -> Workspace:
        self.workspace.ensure()
        return self.workspace

    def change(self, args: Args, perform: Callable[[], None], result: str) -> Output:
        def execute() -> Output:
            perform()
            return Output(result)

        return self.session.effect(args.operation, execute)

    def list_source(self, args: Args, _request: NoArguments) -> Output:
        return self.session.effect(args.operation, lambda: Output("\n".join(self.source().files())))

    def read_source(self, args: Args, request: PathArguments) -> Output:
        name = request.path

        def read() -> Output:
            text = self.source().read(name)
            if len(text) > MAX_SOURCE_CHARS:
                return Output(f"{text[:MAX_SOURCE_CHARS]}\n[cut: showing {MAX_SOURCE_CHARS} of {len(text)} characters]")
            return Output(text)

        return self.session.effect(args.operation, read)

    def write_source(self, args: Args, request: WriteArguments) -> Output:
        path, content = request.path, request.content
        return self.change(args, lambda: self.source().write(path, content), "Written.")

    def edit_source(self, args: Args, request: EditArguments) -> Output:
        path, old, new = request.path, request.old, request.new
        return self.change(args, lambda: self.source().replace(path, old, new), "Edited.")

    def delete_source(self, args: Args, request: PathArguments) -> Output:
        path = request.path
        return self.change(args, lambda: self.source().delete(path), "Deleted.")

    def show_changes(self, args: Args, _request: NoArguments) -> Output:
        def read() -> Output:
            changes = self.source().changes()
            if not changes:
                return Output("No changes yet.")
            return Output("\n".join(changes) + "\n\n" + self.source().diff()[:MAX_SOURCE_CHARS])

        return self.session.effect(args.operation, read)

    def check_changes(self, args: Args, _request: NoArguments) -> Output:
        source = self.source()
        diff = source.diff()
        passed, report = source.validate()
        digest = source_digest(source.root)
        if passed:
            operation = Operation.of(args.tool, {"source_digest": digest, "profile": "affected"})
            result: CheckResult = CheckInterrupted("Runtime checks did not complete.")

            def execute() -> Output:
                nonlocal result
                if source_digest(source.root) != digest:
                    raise SourceError("The source changed before its checks ran; check it again.")
                self.session.step("Running the tests this change affects...")
                result = source.inspect_check(affected=True, cancel=self.session.stop)
                return Output(result.report, ok=result.passed) if isinstance(result, CheckCompleted) else Output(result.reason, ok=False)

            def verify(_: Output) -> ActionVerified | ActionUncertain:
                if isinstance(result, CheckCompleted):
                    detail = "checks passed." if result.passed else "it reported failed checks."
                    return ActionVerified("The runtime check process finished; " + detail)
                return ActionUncertain("The check process was interrupted. Inspect its effects before executing more code.")

            checked = self.session.effect(operation, execute, verify)
            passed, report = checked.ok, checked.text
        if passed and source.diff() != diff:
            passed, report = False, "The workspace changed during its checks; run check_changes again."
        self.checked = Checked(diff, digest) if passed else None
        self.check_failed = not passed
        if self.session.stop.is_set():
            self.checked = None
            return Output("Stopped by the user.", ok=False)
        return Output(report[-6000:], ok=passed)

    def apply_changes(self, args: Args, request: SummaryArguments) -> Output:
        summary, diff = request.summary, self.source().diff()
        if problem := self.source().protected_problem():
            raise SourceError(problem)
        if not diff:
            raise ArgumentError("there are no changes to install.")
        if self.checked is None:
            raise ArgumentError(
                "the last check failed; fix the changes and check again."
                if self.check_failed
                else "run check_changes first; only checked changes can be installed."
            )
        if diff != self.checked.diff:
            raise ArgumentError("the changes have changed since they were checked; run check_changes again.")
        digest = source_digest(self.source().root)
        # The keeper then repeats only the native modules for this checked digest.
        checked = digest if digest == self.checked.digest else None
        install = InstallOperation(summary, digest, str(self.source().live.absolute()), hashlib.sha256(diff.encode("utf-8")).hexdigest())
        operation = described(args.tool, _INSTALL_OPERATION, install)
        if self.session.stop.is_set():
            return Output("Stopped by the user.", ok=False)
        install_root = self.delivery.install_root

        def execute() -> Output:
            if source_digest(self.source().root) != digest:
                raise SourceError("The source changed after its checks; check it again.")
            if problem := self.source().protected_problem():
                raise SourceError(problem)
            if install_root is not None and self.source().root != install_root:
                copy_source(self.source().root, install_root)
            self.session.machine.install(summary, digest, checked)
            self.session.installation_requested(summary)
            return Output("Asked the keeper to install it.")

        return self.session.effect(operation, execute)

    def publish_changes(self, args: Args, request: SummaryArguments) -> Output:
        source = self.source()
        passed, report = source.validate()
        if not passed:
            return Output(report[-6000:], ok=False)

        def execute(perform: Callable[[], str]) -> str:
            return self.session.effect(
                args.operation,
                lambda: Output(perform()),
                lambda _: ActionVerified("The tested candidate was published; remote branch readback matched its commit."),
            ).text

        result = publish_source(
            source.live,
            source.root,
            request.summary,
            self.session.stop.is_set,
            remote=os.environ.get("WORKSPACE_GIT_REMOTE", DEFAULT_REMOTE),
            base=os.environ.get("WORKSPACE_GIT_BASE", "main"),
            branch=self.delivery.branch,
            execute=execute,
        )
        return Output(result)

    def discard_changes(self, args: Args, _request: NoArguments) -> Output:
        def execute() -> Output:
            self.source().reset()
            self.checked, self.check_failed = None, False
            return Output("Discarded: back to the running version.")

        return self.session.effect(args.operation, execute)
