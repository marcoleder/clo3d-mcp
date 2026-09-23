# C++ plugin rewrite: implementation and qualification

Implemented on `feat/native-cpp-plugin`, from the working-copy specification in
[`cpp-bridge-plan.md`](cpp-bridge-plan.md). That specification was already edited
when implementation began and is preserved. This filename did not previously
exist; it now records implementation status and qualification evidence.

The C++ backend is opt-in. The external Python MCP server, all 48 tool names,
protocol 3, Python fallback and ABI-2 shim are retained. There is no dual dispatch,
automatic fallback or retry. Installation and reproducible build commands are
in [`cpp/README.md`](../cpp/README.md).

## Implemented

| Responsibility | Implementation |
|---|---|
| General plugin ABI and lifetime | `PluginEntry.cpp` exports the five entry points from the full SDK's `Samples/ExportPlugin/ExportPlugin.h`. A process-lifetime library reference protects callbacks through host refresh/removal. |
| Scheduling and teardown | `BridgeController` owns a 50 ms application-thread timer, explicit lifecycle states, one guarded command at a time, modal deferral, shared stop command/sentinel and exit cleanup. No application/event loop is created inside CLO. |
| Protocol 3 | `ProtocolQueue`, `PlatformLock`, `JsonFiles`: Python-compatible OS locks, atomic publication and claim rename, stable session readiness, bounded incremental scans, monotonic relative claim/ack deadlines, permission consumption before dispatch and nonreplay after I/O failure. |
| Review safety | `SceneReviewState`: shared existence-based marker, in-memory block during persistence failure, preserved claims, reads/controls while blocked, and verified distinct-project recovery. |
| SDK and handlers | Typed injectable `SdkAdapter`; seven handler files implement the 44 non-session commands. `CommandDispatcher` adds the four session/preview commands and explicit access metadata. Registry names preserve all three wire aliases. |
| Validation/results | Strict JSON types, numeric ranges, enum domains, current bounds, paths, checked setters/imports, STL conversion, raw JSON fallback, failure flags and conservative unknown outcomes after mutating calls. |
| Export options/artifacts | Constructor defaults and the shim's exact option allowlist; direct explicit-option OBJ/FBX/GLB/glTF, turntable colorway overload, tech pack JSON and sidecars, nested snapshots, output structure and freshness checks. |
| Preview | Native refresh returns to the host loop without capturing images. Explicit path selects snapshot mode; no-path calls reset it. Failed automatic capture adds `preview_error` to successful mutation results. Ping exposes refresh/capture counters. |
| Build/package | Separate shim, core, command library, plugin, queue harness and three native test executables; exact Qt 6.10.3; versioned binary, checksum/version manifest and notices; macOS host-framework retargeting and ad-hoc signing. |
| Diagnostics | Bounded rotating logs, opt-in success timings, atomic session/last-command breadcrumbs, unclean-session preservation, and an external local ZIP exporter available through CLI or MCP even after CLO exits. Release symbols are retained for source-level crash analysis. See [diagnostics](diagnostics.md). |
| Client compatibility | Frozen 48 input schemas and executable Python/native handler comparisons. Simulation mode now defaults to automatic (GPU for quality 3); existing explicit integer modes remain valid. `connection.py` retains one publication and a five-second ping deadline. Both backends use a fixed macOS home directory independent of temp environment variables. |

## Lifecycle prerequisite: passed before handler porting

The lifetime spike was compiled and exercised inside CLO before porting scene
handlers. [Captured results](validation/native-lifecycle-2026-09-23.json):

- Native ping returned after the menu callback returned, with all five SDK
  interfaces available, on CLO's application thread and Qt 6.10.3.
- Repeated Start preserved the session. Refresh and removal through Plug-in
  Manager did not stop service or unload callback code. Menus remained usable.
- `stop_bridge` published its result and removed readiness; restart created a
  fresh session. The stop sentinel also stopped service and allowed restart.
- Exiting CLO removed readiness and released the Python-compatible OS lock.

Removing the menu entry deliberately does not stop the service. The extra
library reference lives until process exit; binary upgrades require restarting
CLO. The ABI was taken from the general plugin sample, not `CloEventPlugin`.
The matching toolchain requirement follows the
[CLO build guide](https://developer.clo3d.com/environment.html); registration was
performed with [Plug-in Manager](https://developer.clo3d.com/register.html).

## Validation

Target: CLO **2026.1.224**, macOS **15.8 (24H23)**, arm64, Qt **6.10.3**, Release,
AppleClang **17.0.0.17000604**, deployment target **15.0**.

- Clean native plugin build against the matching full SDK/Qt passed. `otool`
  showed all direct CLOAPIInterface/Qt references pointing to CLO's frameworks;
  `codesign --verify` passed. `nm` showed all five C plugin entry points.
- Clean offline build using only checked-in SDK headers and Qt passed, with no
  CLO runtime link. All three CTest executables passed: protocol, commands and
  exports. Assertions remain active in Release.
- **142 Python tests passed**, including 16 native-client interoperability and
  frozen-contract tests plus 12 shared result-contract cases. The Python static audit also passed (48 command
  parameter mappings, 84 SDK call sites); it does not validate native behavior.
- Native tests cover injected terminal-response/marker failures, monotonic
  deadlines and modal deferral, invalid acknowledgements, restart evidence,
  readiness ownership, nested reentry, strict values/options, unknown imports,
  recovery identity including symlinks, native/snapshot preview, output
  structure/freshness, glTF resources and tech-pack sidecars.
- Review regression tests cover exact-limit and oversized UTF-8 responses,
  successful edits after oversized reads, bounded uncertain-mutation errors,
  and startup/handshake/rejection write failures without false scene review,
  including restart immediately after the failure.
- Pre-merge regressions also cover default simulation modes in both backends,
  legacy Python API arity selection without mutation retries, stdio environment
  filtering, Windows/WSL temp-directory precedence, default ping deadlines,
  delete/copy timeout nonreplay, and option-constructor errors without fallback.
  Schema and Python handler coverage run even when native tests are not built.
  The [pre-merge review record](pre-merge-review-2026-09-23.md) records **173
  passing Python tests**, 3 native suites, the Release rebuild, and each finding's
  disposition; it supersedes the earlier offline test count below the initial build.
- [Full live run](validation/native-live-2026-09-23.json): **48/48 tools**, **52
  successful calls**, **zero failures**, and **170 files produced**. All eight
  export tools passed, including tech-pack project sidecars and referenced
  images. The harness verified scene restoration and stopped the bridge.
- OBJ default/options comparison: default output had **202,544 vertices** and
  **358,446 faces**; excluding avatars produced **52,182 vertices** and **100,351
  faces**. Both had valid geometry. This establishes an option effect on this
  fixture, not complete visual equivalence to the old dialog-driven route.
- [Native preview probe](validation/native-preview-2026-09-23.json): **100 calls**
  (50 reads, 50 color mutations), **50 refresh requests**, **zero preview snapshot
  calls**, and no change to the legacy preview PNG. Five menu open/close input
  checks succeeded during the batch. Client round-trip p50/p95/max were
  **166.3/166.8/173.8 ms**, including protocol handshakes; these are not paint or
  camera latency measurements. Scene restoration passed afterward.
- [Rollback smoke test](validation/native-rollback-2026-09-23.json): after native
  stop, the Python menu bridge served ping and a scene read in the same IPC
  directory, stopped cleanly, then native restarted and stopped successfully.

Live tests use `tools/live_test.py`, the unchanged MCP client and disposable
copies of `test.zprj`. Original scene backups and every scratch output are
retained locally. The harness verifies restoration and stops the bridge.

## Deliberate compatibility details

- `refresh_view` reports a refresh request rather than claiming a completed
  native paint. Default preview creates no image. Explicit snapshot mode keeps
  capture semantics and cost.
- Model exports return `via: cpp_plugin`. FBX/GLB/glTF retain the historical
  SDK-shaped `file_path` alias alongside normalized `file_paths`.
- Uncertain exceptions/postconditions after any mutating SDK call now block
  subsequent writes conservatively. This extends the Python import protections
  to setters and artifact/project writes. A preview-only failure does not block
  a completed mutation.
- A CLO `.zprj` has a proprietary prefix before its ZIP data; archive validation
  reads the end record/central directory instead of requiring a ZIP signature
  at byte zero. This checks structure, not every member's CRC; the live harness
  separately uses Python's `zipfile` integrity checks.
- The SDK documents `"NULL"` as an unsaved project path; a fresh CLO process
  can instead report its built-in `Untitled.zprj`. New-project checks accept
  those representations and require empty patterns/avatars plus the default
  fabric/colorway counts. They cannot establish equivalence of every scene
  property.
- Tech-pack JSON and requested project/package saves must be fresh. CLO may
  reuse referenced textures/thumbnails with unchanged timestamps; those are
  checked for existence and valid structure instead of requiring rewrites.
- Inputs above SDK ranges, boolean indices, malformed vertices/options and
  unsupported Python diagnostics fail explicitly. Messages are bounded at
  16 MiB; export freshness scans allow at most 10,000 existing files. These
  limits are documented and never silently truncate a result.

## Remaining qualification before changing the default

The full handler implementation is present. Native remains opt-in while the
following release gates from the specification remain open:

- Ten-minute idle CPU comparison, continuous camera/selection interaction with
  frame/input gap percentiles, and queue overhead measurements on large real
  queues. Menus responding and successful IPC do not prove paint latency.
- All native/platform dialog and host-busy cases, rather than only Qt modal
  deferral and reentrancy coverage. Synchronous SDK calls still block CLO.
- Independent Windows/MSVC and Windows/WSL build/load, Unicode SDK paths,
  byte-range lock and atomic replacement testing.
- AVAC/APF fixtures, all export option combinations, visual/geometry parity
  across formats, clean-machine installation, and mutation/export parity during
  Python rollback (the lifecycle/read-only switch passed).

No simulation chunking, background SDK calls, socket transport, progress
statuses or automatic timeout recovery were introduced. These remain separate
experiments as specified in the design.

The diagnostics follow-up adds one local support tool, for **48 CLO tools plus
`export_diagnostics`**. It does not add a CLO handler or change protocol 3.
The SDK adapter is built once per bridge start and moved into the dispatcher.
There are now four native test executables, including diagnostics/rotation tests.

### Guided validation of the diagnostics build

[Recorded evidence](validation/native-diagnostics-live-2026-09-23.json) identifies
the tested Release binary. A 61.9-second read probe completed **364 calls without
errors**, with no growth in `bridge.log`. The user reported **"Responsive
throughout"**. Two subsequent passes each exercised **49/49 MCP tools**, with
**53 successful calls**, zero failures, and 170 output files. Both verified scene
restoration and stopped the bridge. Diagnostics exported after stop through MCP
and CLI; ZIP integrity, included-file checksums and the recorded build matched.

The user found editing responsive but could not interact during exports. GLTF
and tech-pack calls took roughly eight seconds each. The first restoration waited
for CLO's Open Project dialog (77.90 seconds including confirmation delay); the
second used the external dialog watcher and restored in 2.76 seconds. The watcher
confirmed one Open Project dialog and no export dialogs. These runs qualify
successful operations and user-observed responsiveness between calls, not an
interactive UI during synchronous SDK exports. The live harness now pauses two
seconds between test actions, adjustable with `--pause=5` or `--pause=0`.

No fatal crash was induced in CLO and no OS crash reports were present. Crash
preservation remains covered by forced termination of the offline test harness;
actual OS dump generation remains an open platform qualification item.

The [final paced live run](validation/native-paced-live-2026-09-23.json) tested
the two-second default between actions: **49/49 tools**, **53 successful calls**,
zero failures, **174 output files**, and **161.21 seconds** elapsed. The user
reported **"Yes, pacing feels good"**. Scene restoration, clean bridge shutdown,
post-stop diagnostics ZIP integrity, checksums and build identity all passed.
The external watcher confirmed the Open Project restoration dialog. Individual
SDK exports remain synchronous; pacing provides interaction gaps between them.
