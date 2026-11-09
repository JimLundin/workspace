# Stubs for untyped dependencies

mypy reads these from `mypy_path`; runtime imports use the installed packages.
A dependency that ships its own types needs no stub here, and an `Any` it
declares is validated where it enters Workspace rather than narrowed by a stub.

The win32more stubs cover only the calls Workspace makes, from the pinned 0.8.7
core and Windows SDK packages, because win32more ships no types. The generated
COM wrappers inherit `ComPtr`; their mixin properties do not imply Python
inheritance between native visual and geometry classes. A `ByReference[T]`
parameter takes `ctypes.byref(...)` of a `T`; the `T` documents the native type.
The Notification Center listener returns the SDK's `IAsyncOperation`; Workspace
polls it through `IAsyncInfo` and `AsyncStatus` instead of awaiting it. Stubs
describe native contracts; Workspace validates nullable pointers and unknown
external values before use. They keep the native API names, which Ruff's
naming configuration allows.
