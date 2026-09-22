# Correctness audit fixes

The [original audit](correctness-audit-2026-09-22.md) describes commit `bbae569`.
This record separates implemented fixes from checks still requiring CLO.
The [review follow-up](review-followup-2026-09-22.md) covers the twelve findings
against `174bbc1`, including cancelled-open protection and partial imports.

| Finding | Resolution | Verification |
|---|---|---|
| 1. Mutations replayed after timeout/error | Publish once; never automatically retry. Report ambiguous outcomes and cancel only unclaimed requests | Delayed mutation, mutation-then-error and restart regressions |
| 2. Concurrent clients overwrite/steal files | UUID request/response files, unique atomic temporary files, single consumer OS lock | Four client processes / 16 calls; duplicate bridge lock regression |
| 3. Live harness false passes | Reject false flags, verify artifacts and selected state changes, discover coverage through tools/list, exercise every export, fail on missing coverage | Offline regressions plus 48/48 tools in live CLO |
| 4. Wrong avatar API | Use native ImportAvatar in add mode for `.avt`, ImportAVAC for `.avac`; reject APF with AVT before mutation | Native import increased avatar count and preserved garment patterns; AVAC/APF pending |
| 5. Empty turntable result | Use explicit current-colorway overload; validate requested paths/dimensions and artifacts | Four distinct 512×512 images; Python/C++ comparisons isolated the broken overload |
| 6. Different default directories | Shared stdlib directory resolver used by plugin, client and harness | Default/override regression |
| 7. Misleading lifecycle/timeout claims | Add stop_bridge, 5-second ping, document shared ownership and non-preemptible native calls | Stop/restart and readiness removal verified in live CLO |
| 8. Startup loses fresh requests | Publish session readiness only after initialization; clients wait for it; reject expired/old-session calls | Startup, expiry, old session and abandoned claim regressions |
| 9. Dropped export options | Reject unavailable/unknown options before export, remove option-losing dialog fallbacks, free native option handles on error | Python fallback and native wrapper regressions |
| 10. False mutation success | Check simulation boolean and copy index, use CopyPatternPieceMove for offsets, verify creation count, propagate false API flags as errors | Offline failure regressions; live state changes passed |
| 11. Windows C symbols not exported | Enable WINDOWS_EXPORT_ALL_SYMBOLS for MSVC | Source configuration fixed; Windows build/load pending |
| 12. Apple build settings in wrong branch | Set the default deployment target before project initialization, respect overrides, use compiler's architecture default | Clean arm64 build; macOS minimum target inspected |

Also corrected the static verifier's evidence claims and default SDK path, stale
export docstrings, unsupported C++ bridge assertions, and tech pack output rules.
Tech pack success now requires newly written, nonempty JSON; a stale existing file
cannot conceal an export that did nothing. Pure Python bridge/shim code is reloaded
on a menu restart; replacing an already loaded native binary can require a CLO restart.

## Offline evidence

- `uv run python -m pytest tests -q`: **95 passed**, including actual MCP stdio
  initialization, discovery of 48 tools, successful ping/stop and propagation of a
  fake CLO simulation failure as an MCP error. No real CLO process is used.
- `uv run python tools/verify_against_clo.py`: **48/48 parameter mappings and 84
  API call sites passed static checks**. This is not proof of live bindings.
- Clean Release shim build with the local CLO 2026.1.224 macOS SDK succeeded.
- Live validation: **48/48 tools, 52 successful calls, zero failures**. Four
  concurrent MCP clients and negative option, preview and tech pack checks passed.

The live run additionally fixed unused-fabric enumeration and nested snapshot
output, and replaced generic ImportFile avatar loading after observing that it
can return true even when its save/discard prompt is cancelled. The native shim
is now ABI 2 and uses a versioned filename to distinguish it from loaded ABI-1
libraries.

See the [live validation report](live-validation-2026-09-22.md) for evidence and
remaining platform/fixture limits, and the [checklist](live-test-checklist.md) to
repeat the run. Both the MCP server and CLO bridge must use protocol 2.
