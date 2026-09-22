# Review of 174bbc1

This records fixes and validation at `d0aeb7f`. The later
[transport follow-up](transport-followup-2026-09-22.md) addresses disk failures,
clock drift, cleanup and option handling, and upgrades both sides to protocol 3.

The review identified real gaps in successful-open verification, partial-import
handling, snapshot validation, shim discovery and failure tests. These are fixed
on `fix/correctness-audit`, targeting `main` in
[the fork's PR #1](https://github.com/marcoleder/clo3d-mcp/pull/1).
The upstream repository has a separate PR namespace.

| Review item | Resolution |
|---|---|
| 1. Cancelled open/import reports success | Both handlers verify `.zprj` against `GetProjectFilePath`. The live harness independently reads back the path before edits, including with an older bridge. Restoration checks both path and baseline pattern/fabric/colorway/avatar state. |
| 2. Restore generic AVT fallback | Deliberately declined: generic `ImportFile` can replace the garment. Postchecks detect damage after it happens; they cannot undo it. AVT requires ready ABI 2; ABI 1 remains usable for exports. Missing/not-ready libraries are retried on later calls. Windows AVT remains unverified. |
| 3–4. Snapshot shapes and nonexistent files | Accept a string, flat paths or nested groups; reject invalid/empty paths, missing files, directories and zero-byte files. Never iterate a string as individual characters. |
| 5. Failed avatar postcondition permits duplicate retry | Report `outcome=unknown`, `retry_safe=false`, `scene_review_required=true`; persist a mutation block across clients and bridge restarts. No automatic rollback is claimed. An already added avatar remains until recovery. |
| 6. Boolean fabric-count overload ambiguity | Use the documented integer `-2` selector for all fabrics. Regression tests distinguish booleans from integer selectors. The earlier live Python/C++ probe did return all fabrics for `False`; wrong overload selection was a risk, not an observed failure on this build. |
| 7. Old shim shadows ABI 2 | Search ABI-2 filenames across all folders first; validate the actual ABI and required symbols, skip unusable candidates, prefer the highest supported ready ABI, and reconsider a cached ABI 1. Explicit `CLO_SHIM_PATH` stays authoritative. |
| 8. AVAC lacks postconditions | AVAC and AVT both require avatar count growth, unchanged pattern names/count and unchanged project path. AVAC/APF success still needs a live fixture. |
| 9. Fabric tools always claim success | Add/import require count growth and a valid returned index; color changes check the SDK boolean. Uncertain fabric additions also block retries. |
| 10. Duplicated failure flags | One stdlib-only contract module is shared by the plugin and live validator. |
| 11. Snapshot compatibility/documentation | Keep legacy `file_path` with the SDK's original shape and add normalized `file_paths`. The tool description documents both. |
| 12. Missing AVT failure tests | Cover ABI 1, native false/negative results, true without count growth, pattern/project changes, exceptions after adding, retry blocking and verified recovery. |

## Recovery contract

`scene-review-required.json` in `CLO3D_MCP_DIR` records an uncertain native
mutation. Reads and bridge shutdown remain available; subsequent mutations fail
before entering the SDK. Inspect CLO, then open a **distinct saved `.zprj`
backup** through `open_file` or `import_file`. Only a successful call with the
expected active path clears the block. A cancelled recovery leaves it in place.
The live harness stops after an uncertain outcome and retains its backup; it
does not queue an automatic restore or repeat a possibly applied command.

Opening the already active `.zprj` is explicitly a no-op (`already_active=true`),
preserving unsaved edits. It cannot clear an uncertain-scene block because a
cancelled reload of that same path cannot be distinguished by path readback.
Generic nonproject imports must change observable scene identity (or camera
state for `.zcmr`); unchanged state produces an uncertain error even if the SDK
returns true. This is conservative: the checks do not prove full geometric or
visual equivalence. Avatar/fabric extensions use their dedicated verified
handlers even through `open_file` and `import_file`.

## Verification

- Offline: **95 tests passed**, using fake CLO APIs, real file IPC and actual MCP
  stdio tests. The real harness is exercised against a false-success open;
  assertions verify that no scene edits or automatic recovery follow it.
- Static verifier: **48/48 mappings**, **84 call sites**. Static checks do not
  prove runtime binding behavior.
- Live revalidation on CLO 2026.1.224 / macOS arm64: **48/48 tools, 52 successful
  calls, zero failures**. The updated project identity gates and restoration
  checks passed, including baseline pattern/fabric/colorway/avatar state. The
  ready ABI-2 shim was selected; AVT, both fabric additions, color setting and
  snapshot export passed. Dangerous partial-failure/cancellation cases are
  injected offline, not into a user scene.

Evidence is retained outside Git in
`/Users/port/Documents/gh/clo3d-mcp-live-2026-09-22/`: `review-suite.log`,
`review-watcher.log`, and `review-run/` containing `results.json`, the original
scene backup, test garment and all 170 output files. The starting empty garment
scene was restored; the bridge and dialog watcher were stopped afterward.
Windows, AVAC/APF and other CLO versions still need separate live validation.
