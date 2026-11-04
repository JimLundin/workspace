# Code quality policies

Tests cover defects in Workspace's decisions, adapters and policy enforcement.
Python language features, built-ins, standard-library implementations and
dependencies' documented functionality are trusted and already tested upstream.
Do not write tests demonstrating lazy imports or another language feature. A
checker test must detect a plausible error in our enforcement, such as accepting
a forbidden interface or issuing a receipt after a policy failure.

Boolean parameters are keyword-only, and a function takes at most five inputs.
Count positional and keyword-only inputs; exclude the bound receiver.

Ruff enforces both through FBT001, FBT002 and PLR0913 (`max-args = 5`).
`scripts/quality.py` also runs those rules before editing tests, including
explicit test selections, so a violation stops the run before a receipt. A
signature that genuinely needs more inputs, such as a composition root or a
native ABI, carries a targeted `# noqa: PLR0913 - <reason>` on its `def` line.
Never suppress whole files or positional Booleans.

Ruff detects ordinary function annotations, including evident Boolean unions,
and Boolean defaults. Keyword-only declarations make both literal and variable
Boolean callers use a name, with type checking validating calls. Generated record
constructors, hidden type aliases, variadic interfaces and dependency/native
contracts also require review. Accurate stubs retain upstream signatures. Keep
necessary native positional binding inside an explicit boundary adapter.

Use a frozen domain record when several inputs really describe one concept.
Splitting independent work is often clearer. Moving unrelated values into an
options object or `**kwargs` only hides the original interface problem.

## Import ownership

Use absolute imports from the owning module, using module-qualified names when
names collide. Ruff's TID252 rule enforces absolute imports during linting; the
editing/CI gate observes relative imports directly in its AST import walk, so
explicit test selections cannot bypass the policy.

The same editing/CI gate rejects new aliased imports, imports inside function or
class bodies, and direct `__all__` forwarding of imported names. These use Python's existing AST parser; Ruff has
no rule that covers this complete project policy. Every finding blocks. Adapters own validation, lifecycle
or adaptation with an explicit contract; they do not forward dependency
symbols. Re-exports are forbidden as review policy, including indirect forwarding
and dynamic exports that static checks cannot reliably detect. Dependency stubs
describe upstream contracts and retain upstream exports.

Qt consumers import directly from PySide6. `desktop_ui/qt_runtime.py` owns the
required Python executor initialization before lazy Qt imports first resolve;
it exports no Qt symbols. Native startup coverage checks the SDK/Qt ordering.

Declare dependencies at module level. Use Python 3.15's `lazy import` or
`lazy from` to defer loading until first use. This preserves visible module
dependencies and native initialization order without imports inside methods.
Launchers run directly on Python 3.15 and lazily resolve product imports after
runtime activation. The editing runner lazily loads its test/native dependencies after both policy gates pass;
the staged native deployment driver can avoid loading test machinery entirely.

## UI independence

`tool.workspace.architecture.headless` names the work frontend, canvas owner and
shared conversation/attention/edit values. The source review follows their full
import routes, including lazy imports and package initializers, and rejects
`desktop_ui`, `PySide6` and `PyQt6`. Native rendering and text preparation enter
through the injected presentation adapter; the canvas client receives commands
and immutable publications from `assistant/work_canvas_contracts.py`.
`ui_private` also rejects presentation imports of concrete work/canvas owners,
including indirect imports through contracts. These declarations supplement process isolation: a
logic owner remains headless even when it shares the desktop process with Qt.

The canvas owner holds its reentrant lock through each read/modify/write operation
and ordered publication. Publish callbacks enqueue observations without waiting
for native rendering. Queue callbacks may read the committed document, and use
this owner's catalog title rather than locking another observation owner. Durable
work publication runs before presentation and survives an unavailable view.
