# Python 3.15 standard-library typing

These are the standard-library stubs shipped in the Pyright 1.1.414 distribution.
That was the latest release on both PyPI and npm when checked on 2026-10-28.
The upstream Apache license is retained in `LICENSE`.

`stdlib/builtins.pyi` omits the incorrect
zero-argument `frozendict.__init__` declaration. Its existing typed `__new__`
overloads already validate native constructor arguments and preserve key/value
types. This matches the declaration in the installed Mypy typeshed. Workspace
can therefore use ordinary native `frozendict(...)` calls, with no runtime
wrapper, constructor workaround, cast or type-checker suppression.

`stdlib/subprocess.pyi` retains the selected `Popen[bytes]` or `Popen[str]`
parameter on its optional stdin/stdout/stderr streams. Upstream's `IO[Any]`
attributes erase the already selected binary/text contract and make the native
taskbar readiness adapter untyped. The constructor overloads and runtime behavior
are unchanged; no subprocess wrapper or type assertion is needed.

Replacing `builtins` as an ordinary module under `stubPath`/`mypy_path` breaks
intrinsic type identity and narrowing. Both checkers instead use their supported
typeshed-directory setting in `pyproject.toml`. The complete 4.1 MB standard-library
stub set is retained because those settings replace the standard-library root;
unrelated Python contracts must remain intact. Third-party packages retain their
installed typing and the focused declarations elsewhere in `typings/`.
The installed Mypy distribution's `mypy-extensions` stub is included because
Mypy requires that compiler-support module in a custom typeshed root. This
vendored directory is hidden so recursive application checking does not treat
standard-library declarations as Workspace source. Both checkers still load
these declarations normally through the configured typeshed root.

These upstream declarations describe Python, rather than new Workspace APIs.
Python and typeshed own their algorithms and library contracts. No tests of
frozen mapping, hashing or Python language semantics are added.

When upgrading, check the bundled `frozendict` declaration first. Remove this
override and both typeshed-directory settings once upstream accepts the native
constructor and preserves subprocess stream types. If an override remains
necessary, refresh the upstream standard-library files and retain only the
required declaration corrections. Keep
the license and record the source version here.
