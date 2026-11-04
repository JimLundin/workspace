# Consumed dependency interfaces

These stubs describe only calls made by Workspace. Pyright uses this
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

The [standard-library overrides](typeshed-overrides/README.md) correct Pyright's
bundled typeshed for the native `frozendict` constructor, subprocess stream types,
ctypes payloads, and registry and URL observations. `scripts/typecheck.py`
builds the patched typeshed before each Pyright run; runtime uses the builtins directly.

The jsonschema stub exposes only `validate`, which raises for an instance the
schema rejects. A meeting test uses it to check the tool schema offered to the
model against payloads the follow-up validator accepts; schema evaluation
belongs to jsonschema.

Watchdog's stubs expose its consumed event fields and observer lifecycle. The
handler protocol records the actual dispatch call used by the native observer;
Workspace owns filtering, batching, check sequencing and preview shutdown.

The win32more stubs cover the consumed desktop-composition and dispatcher
calls from the pinned 0.8.7 core and Windows SDK packages. The generated
COM wrappers inherit `ComPtr`; their mixin properties do not imply Python
inheritance between native visual/geometry classes. Pointer output annotations
describe the SDK's concrete COM pointer conversion and callback ABI. Workspace
callback logic consumes only a writable output slot through a protocol.
The Notification Center listener returns the SDK's `IAsyncOperation`; Workspace
polls it through `IAsyncInfo` and `AsyncStatus` instead of awaiting it, and its
results stay an iterable of `UserNotification` rows.
Unknown external observations remain `object` until validated, with no `Any`,
casts or checker suppressions in the composition logic. These stubs retain the
native API names; runtime still loads the installed dependency.

COM output slots carry their concrete pointer payload; ctypes prototypes
preserve scalar results through `winapi._core.NativeFunction`. Structure fields
are explicitly declared at their effect owners. Stubs describe native contracts;
Workspace validates nullable pointers and unknown external values before use.

Project-owned stubs use native `type` declarations and contain no checker or
lint suppression comments. Native dependency spellings are documented in Ruff's
naming configuration. Typeshed overrides retain their upstream declarations.
