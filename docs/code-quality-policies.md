# Code quality policies

Tests cover defects in Workspace's decisions, adapters and policy enforcement.
Python language features, built-ins, standard-library implementations and
dependencies' documented functionality are trusted and already tested upstream.
Do not write tests demonstrating lazy imports or another language feature. A
checker test must detect a plausible error in our enforcement, such as accepting
a forbidden interface or issuing a receipt after a policy failure.

The policy lives in `AGENTS.md`: Boolean parameters are keyword-only, and three
inputs is the default design target. Count positional and keyword-only inputs;
exclude the bound receiver. A larger interface is a review smell, not an absolute
ban on a cohesive deep module or a required native callback.

`scripts/quality.py` runs Ruff's FBT001, FBT002 and PLR0913 rules before editing
tests, including explicit test selections. New positional Boolean declarations
stop the run before a receipt. New signatures over three inputs produce review
warnings; document their reason alongside the interface. Both CI profiles that
run editing/signature checks install Ruff as a development tool. The application
runtime and protected selfcheck do not acquire a linter dependency.

`quality-migrations.json` records existing findings using an exact source path,
lexical declaration and hash of the parameter structure. Moving lines does not
change a key. Changing a signature or adding a declaration cannot inherit its
entry. Removing an old violation requires removing its stale entry. These entries
are migration debt, not permission to add more positional Booleans or unrelated
parameters. An intentional fixed interface needs a reviewed exact entry and its
actual reason, plus the explanation at its owner; do not suppress whole files.

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
explicit test selections cannot bypass the policy. Relative imports have no
migration exceptions.

The same editing/CI gate rejects new aliased imports, imports inside function or
class bodies, and direct `__all__` forwarding of imported names. These use Python's existing AST parser; Ruff has
no rule that covers this complete project policy. Line-independent exact import
structures join the same migration baseline. Adapters own validation, lifecycle
or adaptation with an explicit contract; they do not forward dependency
symbols. Re-exports are forbidden as review policy, including indirect forwarding
and dynamic exports that static checks cannot reliably detect. Dependency stubs
describe upstream contracts and retain upstream exports.

Qt consumers import directly from PySide6. `assistant/qt_runtime.py` owns the
required Python executor initialization before lazy Qt imports first resolve;
it exports no Qt symbols. Native startup coverage checks the SDK/Qt ordering.

Declare dependencies at module level. Use Python 3.15's `lazy import` or
`lazy from` to defer loading until first use. This preserves visible module
dependencies and native initialization order without imports inside methods.
The Python 3.12 bootstrap keeps ordinary module-level imports. The editing
runner lazily loads its test/native dependencies after both policy gates pass;
the staged native deployment driver can avoid loading test machinery entirely.
