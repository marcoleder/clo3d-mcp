# Live validation — 2026-09-22

CLO 2026.1.224 on macOS arm64, using protocol 2, real stdio MCP clients, and
native shim ABI 2. **All 48 tools were exercised: 52 calls passed, zero failed.**
This verifies the tested inputs and postconditions, not every possible option,
platform or visual property.

## Findings resolved during the live run

| Finding | Evidence | Change |
|---|---|---|
| Newly imported fabrics were absent from counts/lists | Default/true/current-colorway counts stayed at 2 after AddFabric; false/all returned 3 in both Python and C++; the new fabric had index 2 and a readable name | Count/list all fabrics, including unused ones; include names in the list |
| ImportFile was unsafe for AVT | Opening an AVT produced a save/discard prompt; cancelling still returned true | Native ImportAvatar with `bAdd=true`, plus checks that avatar count increases and garment pattern count stays unchanged |
| Snapshot output was nested | ExportSnapshot3D returned `[["…/snap.png"]]`, which the artifact validator correctly rejected as a flat path list | Flatten the SDK's colorway/view groups into `file_paths` |
| Turntable path overload produced no files | The ordinary path overload returned `[]` from both Python and C++. The count-only and explicit-colorway overloads produced images | Use ExportTurntableImagesByColorwayIndex with the current colorway and requested path/dimensions |

Native avatar import added a second avatar while retaining all 14 garment
patterns in the focused probe. The complete suite also checked that pattern
indices/names stayed unchanged across avatar import. AVT now requires the updated
native shim. AVAC/APF routing remains supported but no AVAC/APF fixture was
available for this live session.

## Verified outputs and behavior

- Full suite: 48 distinct MCP tools, 52 successful calls, no failures or missing
  coverage. Fabric add/import/replace/delete and turntable export all passed.
- Four simultaneous independent MCP clients completed 16 pattern-info requests;
  each index and name matched the expected pattern. Exiting those clients left
  the shared bridge alive and responsive.
- Unknown options were rejected for OBJ, FBX, GLB and glTF without creating output
  files. A string supplied for a boolean option and AVT with an APF were rejected.
- OBJ with avatars contained **202,544 vertices / 358,446 faces**; with
  `bExportAvatar=false`, **52,182 vertices / 100,351 faces**.
- FBX binary header verified. GLB version 2, **41,811,232 bytes**, correct total
  length and **36 meshes**. glTF JSON and its external resources passed validation.
- Turntable produced **four different 512×512 PNGs**. Front/side renders were
  visually inspected; the four final outputs have distinct hashes. Snapshot and
  thumbnail artifacts also passed format checks.
- Enabling live preview and renaming a pattern updated the preview image. Preview
  was disabled afterward.
- Tech pack JSON and sidecars were produced. With `m_bSaveZprj=false` and
  `m_bSaveZpac=false`, no project/garment archive sidecars were created and the
  active project path stayed unchanged.
- New project cleared patterns, subsequent import reopened the test garment, and
  the original starting scene was restored. The starting scene was empty; final
  pattern readback matched it.
- `stop_bridge` returned successfully, removed readiness metadata and released
  the bridge loop. The dialog watcher was stopped. Restarting between passes
  published new session IDs.

## Reproduction and evidence

Run the documented harness with the bridge active:

```bash
uv run python tools/live_test.py /absolute/path/garment.zprj --run-live
```

Offline regression suite: **42 passed**. Static verifier: **48/48 parameter
mappings and 73 API call sites passed**. The updated arm64 shim built and loaded
inside CLO with ABI 2.

Local evidence is retained outside Git in
`/Users/port/Documents/gh/clo3d-mcp-live-2026-09-22/`:

- `full-suite.log`: the initial run exposing the remaining problems.
- `probe-results.json`, `probes.log`, `native-probe/`: Python/C++ comparisons.
- `full-suite-fixed.log`, `final-run/results.json`, `final-run/out/`: passing
  run and preserved model/image/archive outputs.
- `acceptance-results.json`, `acceptance.log`: concurrent clients and negative
  input, preview, tech pack and cleanup checks.
- `validation-summary.json`: artifact counts, dimensions and hashes.

Temporary diagnostic hooks were removed from the launcher. No diagnostic native
library is needed by the committed implementation. Large garment/assets are not
committed.

Windows compilation/loading, AVAC/APF inputs, other CLO releases, exhaustive
export-option combinations and full visual fidelity remain outside this run.
