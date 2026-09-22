# Prepared CLO validation

**Status: pending.** The fix branch has been checked offline. CLO was closed
when live validation was attempted: ping failed before any scene changes. Do
not treat the earlier audit's live results as verification of these fixes.
The user requested that subsequent live testing wait until CLO is available.

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
Missing coverage or a failed check makes the exit status nonzero. It uses a real
stdio MCP server. Tests are not a proof of visual fidelity or every tool option.

After a timeout, do not repeat the mutation. The harness stops further mutations
and requests bridge shutdown between commands, but cannot interrupt native code.
Inspect CLO and restore its printed `original-scene.zprj` manually if necessary.
A crash, forced termination or blocked dialog can also prevent automatic restore.

## Acceptance and remaining investigations

| Area | Check in CLO |
|---|---|
| Protocol 2 | Ping after readiness; two independent clients get their own read-only responses; stopping releases the UI; restarting gives a new session |
| Avatar | `.avt` imports through `ImportFile`; avatar readback and visible scene are correct; `.avac` with an APF needs a separate fixture and check |
| Patterns | Copy offset is relative to the original; returned new index is usable; create/copy/delete counts change; rename reads back correctly |
| Simulation | A valid simulation reports success; assess drape visually. Do not use a dangerous native failure to test false returns: that regression is covered offline |
| Options | OBJ without avatar excludes avatar geometry; inspect FBX/GLB/glTF in a viewer; an unknown option fails before export; confirm no-shim fallback rejects supplied options |
| Tech pack | JSON and sidecars exist; explicit project-save flags behave as requested; active project path is understood |
| Lifecycle | `stop_bridge` releases CLO; client exit alone leaves the shared bridge running; modal calls cannot be stopped until the dialog/call returns |
| Turntable | Four 512×512 images, different camera angles and real contents. Empty results must be an MCP error, not a pass |
| Windows | Build with MSVC, inspect exported `clo_*` symbols, load through ctypes inside CLO, then run this same suite |

**Turntable is still unresolved at the CLO API level.** If the corrected harness
still reports no images, retain its arguments, response, bridge log, CLO version
and scene. Compare the SDK's `ExportTurntableImages(path, count, width, height)`
sample and colorway-specific overload in a disposable session. The Python
signature already matched the SDK during the original audit; another arity change
is not justified without evidence. Do not claim a functional fix until real image
outputs have been produced and inspected.

For Codex's native tool list, restart the Codex client after registration/config
changes. The harness uses its own stdio client and needs no Codex restart.
