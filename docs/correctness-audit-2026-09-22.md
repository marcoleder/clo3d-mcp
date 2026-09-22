# Correctness audit — 2026-09-22

Historical baseline report. For subsequent changes and pending verification, see
the [audit resolution record](audit-fixes.md). Line numbers below refer to the
audited commit, not the current implementation.

Reviewed commit `bbae569`, the SDK and notes in `/Users/port/Qt-6.11.2`, the
referenced Claude scratchpad/task logs, and relevant results from the session
transcript. Tested against the running **CLO 2026.1.224 on macOS arm64**.

**Verdict: the shim and much of the integration work hold up, but “all 47 tools
work” does not.** All 47 tools were exercised in this audit. Two returned explicit
failure values: `import_avatar` and `export_turntable`. The other 45 returned
successful responses for the tested inputs; that is not exhaustive verification
of their semantics, error handling, or every option. There are also reproducible
IPC and lifecycle defects that affect otherwise working tools.

## Verification performed

| Check | Result |
|---|---|
| Editable package installation | Successful; registered as `clo3d` in Codex |
| Real MCP stdio initialization and `tools/list` | Successful; 47 tools |
| Existing unit suite | 9 passed using `uv run --with pytest --no-sync python -m pytest tests/ -q` |
| `tools/verify_against_clo.py` | Passed: 47 parameter mappings, 65 API call sites; limitations below |
| Live run covering 47 distinct tools | Two explicit failures; instrumented harness rejects false success flags |
| Native FBX / GLB / glTF | Real files; FBX header, GLB version/length/mesh data, glTF JSON and referenced resources checked |
| OBJ export options | On the full-run garment, default OBJ had 107,264 vertices; `bExportAvatar=False` had 52,188 |
| Unknown shim option | Returned in `rejected_options` |
| Tech pack | Valid JSON plus project, garment, image and texture sidecars |
| Native shim clean build | Successful in a separate build directory; arm64, no Qt dependency, valid signature |
| Installed C++ sample plugins | arm64, valid signatures, dependencies retargeted to CLO's frameworks |
| Qt symbol check | 171 required Qt symbols identified in installed widgets plugin; none missing from CLO's Qt |

The standalone export pass started with 14 patterns, 2 fabrics and 1 colorway.
The full mutation run used a disposable copy of `test.zprj`. Afterwards the saved
pre-test scene was reopened; its pattern names and colorways match the initial
readback. CLO was released from the bridge and the dialog watcher was stopped.

## Findings

### 1. High: retries can execute a modifying command more than once

Location: [connection.py](../src/clo3d_mcp/connection.py), lines 106–125 and
187–189; [bridge dispatcher](../plugin/clo3d_mcp_plugin.py), `process_command`.

Every `CLO3DConnectionError` is retried, including a timeout after execution
started and an explicit error response from CLO. The same request ID is reused,
but the bridge does not remember completed/in-flight IDs. A delayed operation
can therefore execute again after the caller has already received its first
successful response. A handler that changes state and then fails can change it
three times. Deletes are especially problematic because indices can shift.

Reproduced using the actual client and bridge poll loop with isolated fake API
handlers: one successful call produced **two mutations** after a timeout; one
handler error produced **three mutations**. No real garment was used for these
failure probes.

Fix direction: do not automatically replay ambiguous mutations or application
errors. Add request deduplication/ownership before supporting retries. Distinguish
transport failure, application failure and an operation whose outcome is unknown.

### 2. High: independent clients can overwrite requests and consume each other's responses

Location: [connection.py](../src/clo3d_mcp/connection.py), lines 136–185.

All clients share `request.json`, `request.json.tmp` and `response.json` with no
transaction lock. A sender deletes another pending request; a reader removes a
response before checking its ID. Simultaneous writes also race on the same temp
filename. Atomic rename alone does not make the request/response transaction safe.

Concurrent isolated callers reproduced lost requests, `FileNotFoundError` and
timeouts. This applies to separate Codex/Claude/test clients sharing the directory.
The installed FastMCP version currently invokes these synchronous tool functions
on its event loop, so this is not a claim that one server necessarily runs its
own tool calls in parallel.

Fix direction: serialize the whole transaction across processes, or use separate
request/response files keyed by ID and an explicit queue. Do not delete responses
owned by other clients. Until fixed, use one client at a time.

### 3. High: the live harness counts failed operations as passes

Location: [live_test.py](../tools/live_test.py), lines 61–72 and its `run` helper.

`Server.call()` considers any non-error MCP response a success, including
`{"imported": false}` and `{"exported": false}`. The stored historical logs mark
avatar import and turntable export `ok`. The audit's instrumented run rejects
these false values and fails both tools. A direct isolated reproduction also
shows the unmodified harness returning `(True, {"exported": False})`.

The harness enumerates only **45** tools, omits `refresh_view` and
`set_live_preview`, and skips GLB/glTF by default even with a working shim. It does
not verify most postconditions or output contents. The audit explicitly added
the two omitted calls and enabled both GLB/glTF calls.

Fix direction: validate operation-specific flags, resulting state, and actual
files; compare coverage against MCP `tools/list`; report skipped tools separately
from passes. The old logs and a zero exception count cannot establish 47/47.

### 4. Medium: the advertised `.avt` avatar import uses the AVAC API and fails

Location: [plugin handler](../plugin/clo3d_mcp_plugin.py), lines 650–654, and
[server schema](../src/clo3d_mcp/server.py), `import_avatar`.

The MCP tool documents `.avt` input but calls `ImportAVAC`. The SDK describes
that function as importing an AVAC avatar file. On the installed, existing asset
`CLO Assets/Avatar/Female/FV2.1_Mia.avt`, the live call returned `imported: false`.

Fix direction: route supported file types to the appropriate import API and
verify the avatar state afterward. Treat `.avac` plus pose input separately from
the advertised `.avt` workflow. Do not infer that a false return necessarily
means the native API made no partial changes.

### 5. Medium: turntable export is not working in the tested configuration

Location: [plugin handler](../plugin/clo3d_mcp_plugin.py), lines 613–620.

Two live runs requested four 512×512 frames from nonempty garments. Both returned
`exported: false` and produced no turntable files. The static arity check passes
because the call has a valid SDK signature. The root cause inside CLO's API was
not established; it may be an API/platform/runtime limitation rather than a
simple argument-count defect.

Fix direction: establish a working native baseline and its preconditions, then
verify frame count and dimensions. Until then, document the failure instead of
claiming the tool is verified.

### 6. Medium: default directories still disagree on macOS

Location: [connection.py](../src/clo3d_mcp/connection.py), `_find_comm_dir`, and
[plugin](../plugin/clo3d_mcp_plugin.py), `COMM_DIR`.

Without `TEMP` or `CLO3D_MCP_DIR`, the server selects `/tmp/clo3d_mcp` and the
plugin selects `~/clo3d_mcp`. The handoff's project-specific environment override
works around this locally; it did not fix default onboarding. Setting a variable
in an MCP server's environment does not also set it in the already-running CLO.

The Codex installation now explicitly uses `/Users/port/clo3d_mcp`, and README
instructions describe the mismatch. The implementation defaults remain different.

### 7. Medium: automatic release and hard deadline claims are false

Location: [connection.py](../src/clo3d_mcp/connection.py), `disconnect`, and
[plugin](../plugin/clo3d_mcp_plugin.py), `poll_loop` / `run_blocking`.

The ordinary MCP server never writes the stop sentinel; `disconnect()` is a
no-op. Only the custom harness/probes release the bridge automatically. Finishing
a conversation or exiting Codex does not release CLO immediately.

The deadline and stop file are checked **between** handlers. They cannot interrupt
a blocked export, simulation or modal dialog. An isolated handler lasting 0.25 s
outlived a 0.08 s bridge deadline despite a stop signal. Thus the comments promising
that CLO can never remain wedged are not valid.

Also, default timeout is 180 s **per attempt**, up to three attempts plus two
1 s delays: roughly **542 s**, including for the MCP `ping` tool. The separate
connection object's `ping()` helper uses one attempt but is not what that tool
calls. Codex's configured 600 s timeout accommodates current behavior; it does
not make replay safe. README lifecycle/timeout instructions were corrected.

### 8. Medium: startup deletes a legitimately pending request

Location: [plugin](../plugin/clo3d_mcp_plugin.py), `poll_loop` startup cleanup.

The plugin unconditionally deletes existing request and response files when it
starts. A client that submits while the menu launcher is importing/retiring its
previous instance can lose its request and wait until the retry timeout. An
isolated reproduction submits `ping` before startup: the request disappears and
no response is written. One audit run stalled immediately after launch; waiting
for startup before submitting allowed the full run to complete. The reproduction
establishes the race; the exact cause of that one live stall was not instrumented.

Fix direction: expose readiness/session identity, and distinguish an expired
request from a valid request for the new session.

### 9. Medium: no-shim export fallbacks still silently discard caller options

Location: [plugin](../plugin/clo3d_mcp_plugin.py), lines 574–577 and 594–595.

If the shim is absent, GLB/glTF route to the dialog variants without forwarding
or rejecting `params["options"]`. The response can say success despite losing
`bExportAvatar=False`, scale, or other choices. Isolated module doubles reproduced
this for both handlers. The live dialog fallback itself was not retested.

OBJ with options and no shim still calls the missing `NewImportExportOption`
factory and raises `AttributeError`; it bypasses the clearer `_build_export_option`
helper. The native path's `rejected_options` behavior does not fix these branches.

Fix direction: fail explicitly when options cannot be honored; use the same
validation/error contract across native and fallback paths.

### 10. Medium: some handlers ignore native failure results or misdescribe parameters

Location: [plugin](../plugin/clo3d_mcp_plugin.py), lines 357–362 and 665–668;
[SDK pattern API](../sdk/CLOAPIInterface/include/PatternAPIInterface.h),
`CopyPatternPiecePos` / `CopyPatternPieceMove`.

`Simulate` returns `bool`, but the handler discards it and always reports
`simulated: true`. `CopyPatternPiecePos` returns the new index (or a failure
value), but that handler always reports `copied: true`. Both false-success cases
were reproduced with API doubles returning `False` and `-1` respectively.

Additionally, the tool describes `copy_pattern(x, y)` as an offset but uses the
SDK's absolute-position function; the SDK provides `CopyPatternPieceMove` for
offsets. This semantic mismatch is established by the checked-in headers, not by
a position-measuring live test.

Fix direction: preserve native success/index results, verify bounds and
postconditions, and align the advertised coordinate semantics with the API used.

### 11. Medium: Windows shim support is incomplete

Location: [CMakeLists.txt](../cpp/CMakeLists.txt), MSVC branch, and
[clo_shim.cpp](../cpp/clo_shim.cpp), the `extern "C"` functions.

The shim defines no `__declspec(dllexport)`, `.def` file, or CMake
`WINDOWS_EXPORT_ALL_SYMBOLS` setting for its C entry points. `extern "C"` changes
linkage/name mangling; it does not export functions from an MSVC DLL. A default
MSVC build therefore does not provide the function exports ctypes expects.
This is a static finding; no Windows build or runtime test was available.

Fix direction: add explicit C ABI exports or the appropriate CMake export
property and validate the DLL's export table and ctypes loading. See
[CMake's Windows export documentation](https://cmake.org/cmake/help/latest/prop_tgt/WINDOWS_EXPORT_ALL_SYMBOLS.html).

### 12. Medium: macOS target settings are accidentally inside the MSVC branch

Location: [CMakeLists.txt](../cpp/CMakeLists.txt), lines 48–65.

The deployment-target and architecture settings execute only under `elseif(MSVC)`.
They never run on macOS. The clean audit build was arm64 because of the host
default, and its Mach-O minimum OS was **15.0**, not the intended 12.0. The existing
cached build is not evidence that a fresh build applies these settings.

Fix direction: move Apple settings into an Apple branch and set/check target
properties at the appropriate time. Check the SDK library's own deployment
minimum before claiming support for older macOS versions.

## Limits and corrections to the earlier reasoning

- **The static checker is useful but not a binding verifier.** It uses `strings`
  on a binary, whitelists option-constructor names, skips some guarded arity
  mismatches, checks only names/counts rather than argument types, and hardcodes
  this user's SDK path. It passed with every runtime defect above. The notes
  themselves correctly warn elsewhere that `strings` does not prove binding
  availability. It also does not write the `api_map2.json` file the handoff says
  it regenerates.
- **Qt linkage is supported by evidence, ABI compatibility is not proved by a
  symbol diff.** The installed plugins' paths/signatures/arm64 slices check out,
  and the identified Qt dependencies all resolve. Building against 6.11.2 and
  loading 6.10.3 remains outside the compatibility direction Qt promises. Symbol
  presence does not check inline behavior, layouts, private helpers or generated
  metadata. Use matching build/runtime Qt for a supported baseline. See
  [Qt's compatibility statement](https://doc.qt.io/qt-6/qt-releases.html#binary-compatibility).
- **A QTimer would fix idle polling, not make synchronous native operations
  nonblocking.** A timer callback calling a long simulation/export still occupies
  the GUI thread until it returns. Timer lifetime, Python interpreter lifetime
  and long-call responsiveness are separate questions; the timer prototype was
  not built during this audit.
- **Function-name counts do not establish equivalent usable API coverage.** The
  unconstructible option types are already a counterexample. Raw attribute
  totals cannot prove that C++ adds no accessible functionality beyond the four
  exports currently wrapped.
- **Live preview:** snapshot generation and successful refresh calls were
  reproduced. This audit did not repeat the earlier controlled on-screen color
  sequence, so it does not independently establish that every mutation repaints
  visibly under every viewport condition.
- **Tech-pack side effects:** its SDK defaults save `.zprj` and `.zpac` sidecars.
  The live export also changed the active project path to that saved project.
  The requested path is the JSON file, not a directory; sidecars sit alongside
  it. A naive recursive file count under the JSON path reports zero incorrectly.
- **Documentation drift:** `server.py` still tells clients that FBX and OBJ
  options cannot work, despite the shim. The old operational notes still contain
  Script Editor instructions and 45-tool counts superseded elsewhere. The
  original README's `uv sync --dev` did not install pytest because no development
  dependency group exists; the README now shows an explicit pytest runner.

## Evidence and changes made

Local audit artifacts are preserved at
`/Users/port/Documents/gh/clo3d-mcp-audit-2026-09-22/`:

- `full-audit-summary.json`, `full-audit-responses.json`, `full-audit.log`:
  all 47 tool names, raw results and explicit failures.
- `live-export-results.json`, `live-export-validation.json`,
  `full-export-validation.json`, `live-exports/`: export evidence and saved scene.
- `reproduce_findings.py`, `offline-findings.json`: isolated failure reproductions
  against the actual client and bridge; no CLO required.
- `run_full_audit.py`, `live_export_audit.py`: audit drivers. The full driver
  requires a running bridge, the test garment, and deliberate restoration of the
  saved scene; it is not a general replacement for the repository harness.
- `qt-symbol-audit.json`, `shim-build/`: binary/build checks.
- `prior-session-evidence/`, `HANDOFF.md`, `CLAUDE.md`: preserved copies of the
  provided temporary evidence and operational notes.

The full-run generated files remain at
`/var/folders/6l/nhlcgw7x49596j65v38tyc5h0000gn/T/clo3d-live-d3e45s2d/out`;
their validation results are preserved above.

Changes in this review are the editable installation, Codex configuration,
README setup/status corrections, and this report. The runtime defects above
remain open. Prioritize retry/transaction safety and truthful tests, then the
failing tools, lifecycle, fallback options, and platform builds.
