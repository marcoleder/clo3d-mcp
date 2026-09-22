# Prepared CLO validation

**Status: completed on macOS arm64 / CLO 2026.1.224.** All 48 tools passed
(52 calls), including the corrected avatar import, turntable and fabric/snapshot
behavior. See the [live validation report](live-validation-2026-09-22.md).
This checklist remains the procedure for subsequent runs; Windows and AVAC/APF
fixtures still require separate validation.
The [follow-up review](review-followup-2026-09-22.md) documents the additional
project-identity gates, uncertain-outcome handling and regression tests.

Running the harness without `--run-live` only prints preparation instructions;
it does not start an MCP process, contact the bridge, launch CLO or click its UI.

## Before the later session

1. Install the checkout and test dependencies: `uv sync --locked`.
2. Run offline checks: `uv run python -m pytest tests -q` and
   `uv run python tools/verify_against_clo.py`.
3. Build the native shim against the matching SDK using the README commands.
   Keep the complete checkout: the plugin imports its transport from `src/`.
4. Choose a representative `.zprj`, with patterns, fabrics and a colorway. For
   full coverage install at least one `.zfab` and `.avt` under CLO Assets. The
   default asset root is `~/Documents/CLO/CLO Assets`.
5. Save work in CLO before starting. The harness saves another scratch backup,
   opens a test copy, changes it, restores the backup and stops the bridge.
   Saving/restoring changes the active project path to the scratch backup. The
   harness prints and retains all scratch paths.
6. Start CLO manually when testing is wanted. Restart CLO if the native library
   was replaced while it was loaded. Register the blocking launcher and click
   **Plugins → Plug-in → MCP Bridge (serve)**. Both sides must use the same
   `CLO3D_MCP_DIR`. Protocol 1 and protocol 2 cannot be mixed.
7. Be ready to confirm modal dialogs. Optionally run
   `uv run python tools/dialog_watcher.py 900` in a separate terminal on macOS;
   stop it after the run. It only recognizes a limited set of dialogs. Do not
   leave an unrecognized modal dialog unattended.

## Execute only when CLO is available

```bash
uv run python tools/live_test.py /absolute/path/garment.zprj --run-live
```

The harness discovers the tool list, exercises the two preview tools and all
export tools, verifies API failure flags, checks selected state postconditions
and output artifacts, and writes `results.json` in its printed scratch folder.
It independently reads back the active project path before editing the test
copy, and verifies the restored path and baseline scene identities/counts.
Missing coverage or a failed check makes the exit status nonzero. It uses a real
stdio MCP server. Tests are not a proof of visual fidelity or every tool option.

After a timeout or uncertain outcome, do not repeat the mutation. The harness stops further mutations
and requests bridge shutdown between commands, but cannot interrupt native code.
Inspect CLO and restore its printed `original-scene.zprj` manually if necessary.
A crash, forced termination or blocked dialog can also prevent automatic restore.
If the bridge reports `scene_review_required`, inspect the scene and use
`open_file` to load a distinct saved `.zprj` backup. Only verified recovery
clears the persistent mutation block. Opening the already active path is a
no-op and cannot resolve the block.

## Acceptance and remaining investigations

| Area | Check in CLO |
|---|---|
| Protocol 2 | Ping after readiness; two independent clients get their own read-only responses; stopping releases the UI; restarting gives a new session |
| Avatar | `.avt` imports through native ImportAvatar in add mode; avatar readback and visible scene are correct; `.avac` with an APF needs a separate fixture and check |
| Patterns | Copy offset is relative to the original; returned new index is usable; create/copy/delete counts change; rename reads back correctly |
| Simulation | A valid simulation reports success; assess drape visually. Do not use a dangerous native failure to test false returns: that regression is covered offline |
| Options | OBJ without avatar excludes avatar geometry; inspect FBX/GLB/glTF in a viewer; an unknown option fails before export; confirm no-shim fallback rejects supplied options |
| Tech pack | JSON and sidecars exist; explicit project-save flags behave as requested; active project path is understood |
| Lifecycle | `stop_bridge` releases CLO; client exit alone leaves the shared bridge running; modal calls cannot be stopped until the dialog/call returns |
| Turntable | Four 512×512 images, different camera angles and real contents. Empty results must be an MCP error, not a pass |
| Windows | Build with MSVC, inspect exported `clo_*` symbols, load through ctypes inside CLO, then run this same suite |

**Turntable workaround is verified.** The ordinary path overload returned no
images in both Python and C++ on 2026.1.224. The bridge now uses the explicit
current-colorway overload, which produced four distinct 512×512 images. If it
regresses on another CLO release, retain the request, response, bridge log and
scene before comparing overloads; do not mask empty output as success.

For Codex's native tool list, restart the Codex client after registration/config
changes. The harness uses its own stdio client and needs no Codex restart.
