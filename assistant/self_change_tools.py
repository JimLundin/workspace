"""The self-change tool family: the agent edits, checks, publishes and installs Workspace's own source."""

import hashlib
import os
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from assistant.agent_tools import DECLINED, TEXT, Args, ArgumentError, Display, Output, Session, Tool, fixed, schema
from assistant.llm import Json, tool_spec
from assistant.publishing import DEFAULT_REMOTE, publish_source
from assistant.workspace import CheckCompleted, CheckInterrupted, CheckResult, SourceError, Workspace
from automation.actions import Change, Observation, Operation, target
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


def _source_file(arguments: Mapping[str, Json]) -> tuple[str, ...]:
    match arguments.get("path"):
        case str() as path:
            return ("source", target("source", os.path.normcase(os.path.normpath(path.replace("\\", "/")))))
        case _:
            return ("source",)


def _installation(arguments: Mapping[str, Json]) -> tuple[str, ...]:
    """The reviewed digest and destination let a later run verify what the keeper installed."""
    match arguments.get("source_digest"), arguments.get("destination"):
        case str() as digest, str() as destination if len(digest) == 64:
            return ("source", target("installed-root", destination), "source-digest:" + digest)
        case _:
            return ("source",)


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


@dataclass(frozen=True, slots=True)
class Delivery:
    """Where checked changes go: the keeper's install root, and the branch publishing pushes."""

    install_root: Path | None
    branch: str


class SelfChange:
    """The agent's draft of Workspace and what its checks established.

    Mutable by necessity: the checked diff, a failed check and an installation
    request follow the run's tool calls. Only this family's handlers write them.
    """

    __slots__ = ("check_failed", "checked", "delivery", "installing", "session", "workspace")

    def __init__(self, session: Session, workspace: Workspace, delivery: Delivery) -> None:
        self.session, self.workspace, self.delivery = session, workspace, delivery
        self.checked: str | None = None
        """The diff that last passed its checks."""
        self.check_failed = False
        self.installing: str | None = None
        """Set once the keeper has been asked to install: the task is over."""

    def tools(self) -> tuple[Tool, ...]:
        path = schema({"path": TEXT}, ("path",))
        summary = schema({"summary": TEXT}, ("summary",))
        return (
            Tool(
                tool_spec("list_source", "List Workspace's own source files (your workspace copy).", schema({}, ())),
                self.list_source,
                fixed(Observation(("source",))),
                Display.PUBLIC,
            ),
            Tool(
                tool_spec("read_source", "Read one of Workspace's source files. Start with README.md and AGENTS.md.", path),
                self.read_source,
                lambda arguments: Observation(_source_file(arguments)),
                Display.PUBLIC,
            ),
            Tool(
                tool_spec(
                    "write_source",
                    "Write a whole source file in your workspace (new or replaced).",
                    schema({"path": TEXT, "content": TEXT}, ("path", "content")),
                ),
                self.write_source,
                lambda arguments: Change(_source_file(arguments)),
                Display.PUBLIC,
            ),
            Tool(
                tool_spec(
                    "edit_source",
                    "Replace text that appears exactly once in a source file in your workspace.",
                    schema({"path": TEXT, "old": TEXT, "new": TEXT}, ("path", "old", "new")),
                ),
                self.edit_source,
                lambda arguments: Change(_source_file(arguments)),
                Display.PUBLIC,
            ),
            Tool(
                tool_spec("delete_source", "Delete a source file in your workspace.", path),
                self.delete_source,
                lambda arguments: Change(_source_file(arguments)),
                Display.PUBLIC,
            ),
            Tool(
                tool_spec("show_changes", "Your changes so far, as a diff against the running workspace.", schema({}, ())),
                self.show_changes,
                fixed(Observation(("source", _SOURCE_TREE))),
                Display.PUBLIC,
            ),
            Tool(
                tool_spec(
                    "check_changes",
                    "Run fast editing checks. The keeper runs full Windows checks before install; in approval mode, checks follow review.",
                    schema({}, ()),
                ),
                self.check_changes,
                fixed(Change(("exclusive", _SOURCE_TREE))),
                Display.PUBLIC,
            ),
            Tool(
                tool_spec(
                    "apply_changes",
                    "Submit checked changes to the keeper: it tests a frozen copy and installs if they pass. "
                    "If they fail to start or crash, they're undone automatically.",
                    summary,
                ),
                self.apply_changes,
                lambda arguments: Change(_installation(arguments)),
                Display.PUBLIC,
            ),
            Tool(
                tool_spec(
                    "publish_changes",
                    "Test, commit and push requested source changes to a new Git branch; main and running source stay unchanged.",
                    summary,
                ),
                self.publish_changes,
                fixed(Change(("exclusive",))),
                Display.PUBLIC,
            ),
            Tool(
                tool_spec("discard_changes", "Throw away your changes: back to the running version.", schema({}, ())),
                self.discard_changes,
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

    def list_source(self, args: Args) -> Output:
        return self.session.effect(args.operation, lambda: Output("\n".join(self.source().files())))

    def read_source(self, args: Args) -> Output:
        name = args.text("path")

        def read() -> Output:
            text = self.source().read(name)
            if len(text) > MAX_SOURCE_CHARS:
                return Output(f"{text[:MAX_SOURCE_CHARS]}\n[cut: showing {MAX_SOURCE_CHARS} of {len(text)} characters]")
            return Output(text)

        return self.session.effect(args.operation, read)

    def write_source(self, args: Args) -> Output:
        path, content = args.text("path"), args.text("content")
        return self.change(args, lambda: self.source().write(path, content), "Written.")

    def edit_source(self, args: Args) -> Output:
        path, old, new = args.text("path"), args.text("old"), args.text("new")
        return self.change(args, lambda: self.source().replace(path, old, new), "Edited.")

    def delete_source(self, args: Args) -> Output:
        path = args.text("path")
        return self.change(args, lambda: self.source().delete(path), "Deleted.")

    def show_changes(self, args: Args) -> Output:
        def read() -> Output:
            changes = self.source().changes()
            if not changes:
                return Output("No changes yet.")
            return Output("\n".join(changes) + "\n\n" + self.source().diff()[:MAX_SOURCE_CHARS])

        return self.session.effect(args.operation, read)

    def check_changes(self, args: Args) -> Output:
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

    def apply_changes(self, args: Args) -> Output:
        summary, diff = args.text("summary"), self.source().diff()
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
        operation = Operation.of(
            args.tool,
            {
                **args.values,
                "source_digest": digest,
                "destination": str(self.source().live.absolute()),
                "diff_sha256": hashlib.sha256(diff.encode("utf-8")).hexdigest(),
            },
        )
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
            self.installing = summary
            return Output("Asked the keeper to install it.")

        return self.session.effect(operation, execute)

    def publish_changes(self, args: Args) -> Output:
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
            args.text("summary"),
            approve,
            self.session.stop.is_set,
            remote=os.environ.get("WORKSPACE_GIT_REMOTE", DEFAULT_REMOTE),
            base=os.environ.get("WORKSPACE_GIT_BASE", "main"),
            branch=self.delivery.branch,
            execute=execute,
        )
        return Output(result)

    def discard_changes(self, args: Args) -> Output:
        def execute() -> Output:
            self.source().reset()
            self.checked, self.check_failed = None, False
            return Output("Discarded: back to the running version.")

        return self.session.effect(args.operation, execute)
