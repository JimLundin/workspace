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

`typeshed.patch` corrects Pyright's bundled standard-library typeshed.
`scripts/typecheck.py` copies that typeshed into the gitignored
`.workspace-typeshed/`, applies the patch with `git apply` and points Pyright's
`typeshedPath` at it. A hunk whose upstream context moved stops the build, so a
Pyright upgrade cannot silently revert an upstream fix. Replacing `builtins` as
an ordinary module under `stubPath` breaks intrinsic type identity, which is
why the patch goes through `typeshedPath`. The corrections:

- `builtins.pyi` drops the incorrect zero-argument `frozendict.__init__`; the
  typed `__new__` overloads already validate constructor arguments, so
  Workspace calls `frozendict(...)` directly.
- `subprocess.pyi` keeps the selected `Popen[bytes]` or `Popen[str]` parameter
  on the stdin/stdout/stderr streams instead of `IO[Any]`.
- `_ctypes.pyi` and `ctypes/__init__.pyi` preserve the payload of `byref` and
  scalar `WINFUNCTYPE` results; native structure construction accepts external
  values as `object`.
- `winreg.pyi` and `urllib/request.pyi` expose queried values and URL responses
  as `object`, so they are validated instead of inferred as `Any`.

After a Pyright upgrade that rejects the patch, regenerate it: copy the new
upstream files to `a/`, the corrected ones to `b/`, and run
`git diff --no-index --no-prefix a b`. Drop a hunk once upstream carries the
correction. The upstream typeshed is Apache-2.0 licensed; the build copies its
`LICENSE`.

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
naming configuration.
