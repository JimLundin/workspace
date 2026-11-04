# Standard-library typeshed overrides

Pyright reads the standard library from `typings/.workspace-typeshed`, which
`python -m scripts.typecheck` builds from the installed Pyright's bundled
typeshed with these files copied over it. The build directory is gitignored and
rebuilt whenever the Pyright version or an override changes. Each override is a
whole upstream file with a small correction; the build refuses to apply one when
Pyright ships a different upstream file than the override was made from.

- `stdlib/builtins.pyi` omits the incorrect zero-argument `frozendict.__init__`.
  The typed `__new__` overloads already validate native constructor arguments,
  so Workspace calls `frozendict(...)` directly.
- `stdlib/subprocess.pyi` keeps the selected `Popen[bytes]` or `Popen[str]`
  parameter on the optional stdin/stdout/stderr streams instead of `IO[Any]`.
- `stdlib/_ctypes.pyi` and `stdlib/ctypes/__init__.pyi` preserve the payload of
  `byref` and scalar `WINFUNCTYPE` results. Native structure construction
  accepts external values as `object`.
- `stdlib/winreg.pyi` and `stdlib/urllib/request.pyi` expose queried values and
  URL responses as `object`, so they are validated instead of inferred as `Any`.

Replacing `builtins` as an ordinary module under `stubPath` breaks intrinsic type
identity, so Pyright uses its supported `typeshedPath` setting instead.

When upgrading Pyright, re-derive each override from the new upstream file and
update `UPSTREAM` in `scripts/typecheck.py`. Delete an override, and eventually
this folder and `typeshedPath`, once upstream carries the correction. The
upstream typeshed is Apache-2.0 licensed; the build copies its `LICENSE`.
