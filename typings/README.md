# Consumed dependency interfaces

These stubs describe only calls made by Workspace. Both type checkers use this
directory; runtime imports continue to use the installed packages.

Hypothesis's `given` and `composite` stubs describe our single-argument,
synchronous properties and their zero-argument wrappers. They retain the
generated value's type instead of erasing it to `Any`. Generation, shrinking and
execution still belong to Hypothesis.

The inspection stub exposes unknown member values as `object`. Pattern matching
and signature validation establish the test-call interface before invocation.
It does not claim that an arbitrary discovered member is a test.

The TOML stub exposes only the consumed `loads` call. Nested parsed values remain
`object` until the architecture configuration schema validates them.

The caching stub preserves callable parameters and results and exposes the
cache clearing used by icon owners. The callback stub covers binding one leading
argument and retains the remaining parameters and result type.

Extend a stub only when consuming another API. Check its signature against the
pinned dependency's source and exercise our integration; stubs must not assert
that external data already satisfies a domain schema.

The [Python 3.15 typeshed override](.workspace-typeshed/README.md) retains Pyright 1.1.414's
standard-library contracts and corrects its native `frozendict` constructor.
Both checkers select it through their supported typeshed-directory settings;
runtime uses the builtin directly. Python's frozen mapping implementation is
trusted, without library tests.

Watchdog's stubs expose its consumed event fields and observer lifecycle. The
handler protocol records the actual dispatch call used by the native observer;
Workspace owns filtering, batching, check sequencing and preview shutdown.

The win32more stubs cover the consumed desktop-composition, dispatcher and
Direct2D calls from the pinned 0.8.7 core and Windows SDK packages. The generated
COM wrappers inherit `ComPtr`; their mixin properties do not imply Python
inheritance between native visual/geometry classes. Pointer output annotations
describe the SDK's concrete COM pointer conversion and callback ABI. Workspace
callback logic consumes only a writable output slot through a protocol.
Unknown external observations remain `object` until validated, with no `Any`,
casts or checker suppressions in the composition logic. These stubs retain the
native API names; runtime still loads the installed dependency.
