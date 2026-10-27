# Dependencies before property tests

Before adding property tests, establish who owns the behavior. Prefer a focused
existing dependency for reusable functionality when its footprint, supported
runtime and interface fit. Test Workspace's adapter and domain contracts;
leave the dependency's algorithms to its own tests. If no suitable dependency
fits the current need, keep the implementation local and test our invariants.

## Audio dependency review

Workspace currently converts signed 16/24/32-bit and float32 PCM, downmixes
one to eight channels, and publishes continuous input/output frame clocks.
Floating-point headroom is preserved through mixing and interpolation before
final int16 clipping. The recording mixer owns a bounded two-second timeline,
late-packet decisions and clipping after contributions have been accumulated.

Primary package metadata checked on 2026-10-27:

| Candidate | Dependency footprint and runtime | Fit for the current converter |
| --- | --- | --- |
| [audioop-lts 0.2.2](https://pypi.org/pypi/audioop-lts/0.2.2/json) | No dependencies. Windows x64 `cp313-abi3` wheel: 30,503 bytes compressed, 69,222 bytes of uncompressed archive files. Python >=3.13; PSF-2.0. | Stateful integer PCM conversion is small, but float32 and general downmixing still need our implementation. |
| [soxr 1.1.0](https://pypi.org/pypi/soxr/1.1.0/json) | Windows x64 `cp312-abi3` wheel: 174,357 bytes; requires NumPy. | Supports float32 and streaming, but output buffering/delay and final flushing require a broader timeline adapter. |
| [miniaudio 1.71](https://pypi.org/pypi/miniaudio/1.71/json) | Requires CFFI, which also requires pycparser on CPython. No published CPython 3.15 or stable-ABI Windows wheel; CPython 3.14 x64 wheel: 281,740 bytes. | Public raw-frame conversion is batch based; retaining resampling state across our packets needs additional native integration. |
| [samplerate 0.2.4](https://pypi.org/pypi/samplerate/0.2.4/json) | Requires NumPy. No published CPython 3.15 or stable-ABI Windows wheel; CPython 3.14 x64 wheel: 1,467,602 bytes. | A streaming resampler exists, but it brings a larger runtime addition and a Windows build requirement for our interpreter. |
| [SciPy 1.18.1](https://pypi.org/pypi/scipy/1.18.1/json) | Windows x64 CPython 3.15 wheel: 37,361,483 bytes, plus NumPy. | Its broad scientific surface is disproportionate to this small audio module. |

[NumPy 2.5.4](https://pypi.org/pypi/numpy/2.5.4/json) alone has a
12,703,085-byte Windows x64 CPython 3.15 wheel. Archive sizes describe download
cost, not the complete installed footprint.

The [audioop-lts implementation](https://github.com/AbstractUmbra/audioop/blob/main/audioop/_audioop.c)
uses a reduced integer phase and returns immutable resampling state. Its
[documented sample formats](https://github.com/AbstractUmbra/audioop/blob/main/docs/audioop.rst)
are signed integers; `tomono` accepts stereo. Narrowing uses shifts and
interpolation has different rounding from our converter. Those numeric
differences are informative, not an immutable product requirement. More
materially, adapting float32 through an integer input can clip before
interpolation and lose headroom. An adapter would still own normalization,
general channel mixing, final clipping and our sample-clock observations.

The [SoXR streaming API](https://github.com/dofuuz/python-soxr/blob/main/src/soxr/__init__.py)
exposes pending output delay and a final `last=True` flush; its
[README](https://github.com/dofuuz/python-soxr/blob/main/README.md) explicitly
warns that chunks can produce no output until later. Miniaudio's published
source archive shows `convert_frames` calling a C converter initialized and
uninitialized for each call; the
[Python API](https://github.com/irmen/pyminiaudio/blob/master/miniaudio.py)
does not expose a persistent raw-PCM resampler.

Retain the small current converter for this change. These candidates do not
replace its complete interface without enough remaining adaptation or runtime
change to justify a separate audio task. Keep the mixer's timeline locally too:
`audioop.add` clips each addition, whereas Workspace accumulates contributions
before clipping on publication.

## Workspace-owned properties

The protocol's tool/app number assignment and indicator bits are Workspace
policy, not a standard serialization algorithm a dependency can determine.
Existing exhaustive indicator tests already cover its small domain. Session
identity, reply resolution and cancellation rules are also product decisions;
a generic state-machine framework would still require those rules.

Generated tests should therefore exercise our audio packet/clock behavior and
session transitions. Use valid domain inputs, fresh effect owners per test case
and immutable observations. Preserve known-value examples where a property
could miss matching implementation mistakes. Add coverage for plausible bugs,
not for Python, frozen dataclasses or dependency behavior itself.

## Generation tool

[Hypothesis 6.170.12](https://pypi.org/pypi/hypothesis/6.170.12/json) is the
development-only generator. Its standard install has one dependency,
[sortedcontainers 2.4.0](https://pypi.org/pypi/sortedcontainers/2.4.0/json),
which has no dependencies. Combined Windows wheels are 720,153 bytes compressed
and contain 2,256,660 bytes of uncompressed files. Optional NumPy, pandas,
Django and pytest integrations are unnecessary.

Hypothesis tests remain regular callable Python functions
([official quickstart](https://github.com/HypothesisWorks/hypothesis/blob/master/hypothesis/docs/quickstart.rst)).
The [changelog](https://github.com/HypothesisWorks/hypothesis/blob/master/hypothesis/docs/changelog.rst)
records Python 3.15 support in 6.165.7. Native wheels avoid the Rust toolchain
required for source builds.

Bound valid input sizes and passing example counts; retain shrinking.
Explicit `derandomize=True` fixes generated inputs until the test, Python or
Hypothesis changes, and `database=None` avoids a local example store. The
[`settings` reference](https://github.com/HypothesisWorks/hypothesis/blob/master/hypothesis/src/hypothesis/_settings.py)
explains that `max_examples` bounds successful valid cases, not all rejection or
shrinking calls. A per-case `deadline` is not a whole-run timeout.

Generated tests live under `tests/properties/`. Editing selection includes nested
test modules and CI runs these properties in addition to its full selfcheck.
Protected flat selfcheck discovery stays unchanged, and the application bundle
has no property-testing dependency. The generators publish frozen records,
tuples and bytes. Narrow stubs retain the consumed Hypothesis types; the
campaign helper configures the library without casts or type suppressions.

## Local verification

The disposable native audioop-lts experiment imported successfully on Windows
Python 3.15.1. It demonstrated different interpolation rounding for the input
`(1, 2)` at 8 kHz to 16 kHz. Workspace's float32 `(2, 0)` example also exposes why
premature clipping changes an interpolated output. These are investigation
results, not new tests of audioop's documented behavior.

On native Windows Python 3.15.1, 75 focused checks pass, including both generated
properties and runner, architecture, bundle, source-release and protected-gate
contracts. The changed tooling and generated tests pass strict Mypy and Pyright;
repository Ruff passes. Broader pre-existing typing debt is outside this result.

Each property detects a deliberately seeded Workspace fault: dropping the carried
audio sample, and ignoring request identity during reply resolution. Both
campaigns have a passing baseline and one detected fault, with no survivors,
timeouts or collection errors. These establish focused test sensitivity, not a
whole-codebase mutation score. Campaign evidence stays in Windows Temp.
