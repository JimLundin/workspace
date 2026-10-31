"""The self-change tool family: the agent edits, checks, publishes and installs Workspace's own source."""

import hashlib
import os
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Final, Protocol

from pydantic import Field, TypeAdapter

from assistant.agent_tools import (
    DECLINED,
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
from assistant.publishing import DEFAULT_REMOTE, publish_source
from assistant.workspace import CheckCompleted, CheckInterrupted, CheckResult, SourceError, Workspace
from automation.actions import Change, Classification, Observation, Operation, target
from automation.json_value import Json
from automation.store import TaskStore
from automation.task import ActionUncertain, ActionVerified, Blocked, Claim, Waiting
from keeper import copy_source, source_digest

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
    "The keeper tests a frozen copy, installs it, restarts Workspace and undoes failures. "
    "keeper.py, selfcheck.py, runtime.py, workspace.pyw and bundled dependencies are protected; edit through the source tools. "
    "Only publish when the user requests it; call publish_changes before apply_changes ends the task. "
    "Publishing tests a frozen copy and pushes a new branch; it does not install or merge into main."
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
    """The install apply_changes requests: its summary, the reviewed digest and the destination."""

    summary: str
    source_digest: Annotated[str, Field(min_length=64, max_length=64)]
    destination: str
    diff_sha256: str


_INSTALL_OPERATION: Final = TypeAdapter(InstallOperation)


def _installation(operation: InstallOperation) -> tuple[str, ...]:
    """The reviewed digest and destination let a later run verify what the keeper installed."""
    return ("source", target("installed-root", operation.destination), "source-digest:" + operation.source_digest)


def verified_installation(store: TaskStore, claim: Claim, live: Path) -> Waiting | None:
    """Finish a requested installation when the running source matches its checked digest."""
    for action in store.unverified_actions(claim.task.id):
        if action.specification.tool != _INSTALLATION:
            continue
        expected = "source-digest:" + source_digest(live)
        location = target("installed-root", str(live.absolute()))
        if expected not in action.specification.resources or location not in action.specification.resources:
            return Waiting(
                Blocked("The keeper's installed source does not match the requested update. Inspect its installation result before retrying.")
            )
        verified = ActionVerified("The running source matches the checked installation's SHA-256 digest.")
        if store.finish_action(action.id, verified, at=time.time()) is None:
            return Waiting(Blocked("The installed source matched, but verification could not be recorded. Resume to inspect it again."))
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


class SelfChange:
    """The agent's draft of Workspace and what its checks established.

    Mutable by necessity: the checked diff and a failed check follow the run's
    tool calls. Only this family's handlers write them.
    """

    __slots__ = ("check_failed", "checked", "delivery", "session", "workspace")

    def __init__(self, session: Installer, workspace: Workspace, delivery: Delivery) -> None:
        self.session, self.workspace, self.delivery = session, workspace, delivery
        self.checked: str | None = None
        """The diff that last passed its checks."""
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
                    "Run fast editing checks. The keeper runs full Windows checks before install; in approval mode, checks follow review.",
                    NO_ARGUMENTS,
                ),
                typed_run(NO_ARGUMENTS, self.check_changes),
                fixed(Change(("exclusive", _SOURCE_TREE))),
                Display.PUBLIC,
            ),
            Tool(
                argument_spec(
                    "apply_changes",
                    "Submit checked changes to the keeper: it tests a frozen copy and installs if they pass. "
                    "If they fail to start or crash, they're undone automatically.",
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
        if passed:
            digest = source_digest(source.root)
            operation = Operation.of(args.tool, {"source_digest": digest, "profile": "fast"})
            if not self.session.approve(operation, "Run Workspace's checks?", "Run this frozen source and its tests?\n\n" + diff):
                return Output(DECLINED, ok=False)
            result: CheckResult = CheckInterrupted("Runtime checks did not complete.")

            def execute() -> Output:
                nonlocal result
                if source_digest(source.root) != digest:
                    raise SourceError("The source changed after review; check it again.")
                self.session.step("Running Workspace's fast editing checks...")
                result = source.inspect_check(fast=True, cancel=self.session.stop)
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
        self.checked = diff if passed else None
        self.check_failed = not passed
        if self.session.stop.is_set():
            self.checked = None
            return Output("Stopped by the user.", ok=False)
        return Output(report[-6000:], ok=passed)

    def apply_changes(self, args: Args, request: SummaryArguments) -> Output:
        summary, diff = request.summary, self.source().diff()
        if not diff:
            raise ArgumentError("there are no changes to install.")
        if self.checked is None:
            raise ArgumentError(
                "the last check failed; fix the changes and check again."
                if self.check_failed
                else "run check_changes first; only checked changes can be installed."
            )
        if diff != self.checked:
            raise ArgumentError("the changes have changed since they were checked; run check_changes again.")
        digest = source_digest(self.source().root)
        install = InstallOperation(summary, digest, str(self.source().live.absolute()), hashlib.sha256(diff.encode("utf-8")).hexdigest())
        operation = described(args.tool, _INSTALL_OPERATION, install)
        if not self.session.approve(operation, "Install workspace changes?", summary + "\n\n" + diff):
            return Output(DECLINED, ok=False)
        if self.session.stop.is_set():
            return Output("Stopped by the user.", ok=False)
        install_root = self.delivery.install_root

        def execute() -> Output:
            if source_digest(self.source().root) != digest:
                raise SourceError("The source changed after review; check and review it again.")
            if install_root is not None and self.source().root != install_root:
                copy_source(self.source().root, install_root)
            self.session.machine.install(summary)
            self.session.installation_requested(summary)
            return Output("Asked the keeper to install it.")

        return self.session.effect(operation, execute)

    def publish_changes(self, args: Args, request: SummaryArguments) -> Output:
        source = self.source()
        passed, report = source.validate()
        if not passed:
            return Output(report[-6000:], ok=False)
        reviewed = args.operation

        def approve(title: str, detail: str) -> bool:
            # The publication review is part of the operation it approves and records.
            nonlocal reviewed
            reviewed = Operation.of(args.tool, {**args.values, "publication_review": detail})
            return self.session.approve(reviewed, title, detail)

        def execute(perform: Callable[[], str]) -> str:
            return self.session.effect(
                reviewed,
                lambda: Output(perform()),
                lambda _: ActionVerified("The tested candidate was published; remote branch readback matched its commit."),
            ).text

        result = publish_source(
            source.live,
            source.root,
            request.summary,
            approve,
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
