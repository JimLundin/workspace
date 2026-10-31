# Test execution ownership

The editing runner keeps native UI tests in one sequential desktop lane. Four
standard-library process workers own the explicitly reviewed portable modules
in `scripts/check.py`. Each worker initializes the SDK once and reuses that
interpreter across complete modules. Tests within a module remain sequential;
each function retains its own files, stores, adapters and cleanup. New modules
remain sequential until their effects are reviewed.

All native modules run after those workers exit.
Their provider/process startup slowed in the first expanded-pool measurement.
The strict overall-deadline HTTP module runs in that quiet phase too: its
half-second budget must not be consumed by competing SDK initialization before
the fixture receives the request. The streaming module also runs there: its
bounded tool/event handshakes took 3.40 seconds and missed the three-second start
deadline during the combined full run, then passed in 1.75 seconds in the focused
run without the worker pool. Its assertions and deadlines are unchanged.
The remaining non-native sequential modules can overlap the portable phase.
Narrow checks retain their selected order without pool startup.

The additional inventory was reviewed against these resource owners:

| Modules | Effects and isolation |
| --- | --- |
| `test_outlook` | Fictional Outlook command adapter, MIME/JSON files in each temporary directory; one Python command fixture. No Outlook COM session. |
| `test_meetings`, `test_meeting_events` | Generated PCM capture adapter, temporary meeting journals/transcripts, explicitly supplied archive, localhost transcription fixture or explicit transcription operation. No microphone or loopback capture. |
| `test_selfcheck`, `test_workspace` | Real candidate interpreters and source files under each temporary directory. The checked repository supplies runner source only. No installed application updates. |
| `test_computer_tools`, `test_background_agent`, `test_features` | Explicit fake machine/window adapters, real SDK calls to private localhost endpoints. No native windows, browser launches or input injection. |
| `test_llm` | Loopback HTTP servers with OS-assigned ports, bounded real clients, fixture credentials and explicit shutdown. |
| `test_feed_triage_service`, `test_local_bridge` | Private loopback transports and temporary endpoint files; fictional sources, explicit stores/callbacks/waits. No installation bridge file. |
| `test_work_execution`, `test_work_agent`, `test_work_submissions` | Temporary SQLite journals, private candidate source, explicit bridge/window/machine adapters. Worker threads and transport servers close before their fixture exits. |
| `test_commands` | Python child processes owned by the real command runner's jobs, temporary marker files and OS-assigned loopback ports. Cancellation closes only owned children. |
| `test_project_context`, `test_routines` | Temporary SQLite journals and watched files, explicit timestamps and transcript observations. |
| `test_keeper` | Real temporary source/version directories with explicit fake child/check/world adapters. No keeper or installed-client launch. |
| `test_source_analysis` | Temporary source/configuration and explicit cache directory, real Ruff subprocesses. |

The original nine reviewed modules retain their placement. The new 20 modules
accounted for roughly 74 seconds of sequential bodies in the first full
baseline and 58 seconds in its warmed repeat. That is available work to overlap,
not a promised elapsed reduction:
worker startup, CPU/storage contention and the native lane still set the total.
The protected selfcheck and CI entry points retain their original execution.

## Coordinator and desktop handoff

On Windows, the editing CLI owns policy review, initial/final source hashes,
diagnostic publication and the success receipt. Its native executor child owns
compile/import/test execution and may relaunch onto the private desktop. Checks
already on that desktop execute directly, avoiding another executor startup
for each watch check. That
relaunch does not rerun the CLI's source reviews. The same validated native
result handoff is used from WSL. The native regression observes actual worker
process exit before its desktop fixture begins, in addition to single source
review, exact execution and receipt publication.

Desktop verification is owned by `scripts/native_desktop.py` and uses three
Win32 observations through ctypes. Native SDK imports needed to create the desktop and own the process job
are lazy. This avoids populating Hypothesis's loaded-module constant catalog
with native SDK sources before generated domain checks. Desktop/process ownership,
stream/argument preservation and exit-status propagation keep their real native
integration coverage.

## Fixture work

Queue saturation uses one actual submission and 255 ordinary observations to fill
the same 256-slot public input interface. It checks overflow rejection, Stop's
reserved path, cancellation of the actual task and completion of every accepted
observation. Separate ordering tests retain requests accepted around Stop. SQLite
durability and product queue capacity are unchanged.

Mixed-font native text fitting checks each rendered line boundary, one pixel
below and above it, zero and the whole document. Each result must be the largest
complete rendered boundary that fits. This covers decisions without hundreds of
equivalent integer heights.

The copied-source SDK/Qt smoke copies production packages and root Python modules
into a fresh directory. It verifies runtime/SDK/UI imports originate there and Qt
originates in the inherited bundle, then pumps and closes the real event loop in
a fresh interpreter. Keeper's exact-mirroring tests separately cover its complete
source inventory. Fresh-process shutdown and initialization-order checks remain.
