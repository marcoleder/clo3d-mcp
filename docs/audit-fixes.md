# Correctness audit fixes

The [original audit](correctness-audit-2026-09-22.md) describes commit `bbae569`.
This record separates implemented fixes from checks still requiring CLO.

| Finding | Resolution | Verification |
|---|---|---|
| 1. Mutations replayed after timeout/error | Publish once; never automatically retry. Report ambiguous outcomes and cancel only unclaimed requests | Delayed mutation, mutation-then-error and restart regressions |
| 2. Concurrent clients overwrite/steal files | UUID request/response files, unique atomic temporary files, single consumer OS lock | Four client processes / 16 calls; duplicate bridge lock regression |
| 3. Live harness false passes | Reject false flags, verify artifacts and selected state changes, discover coverage through tools/list, exercise every export, fail on missing coverage | Offline validator tests and real stdio MCP against a fake CLO bridge; live run pending |
| 4. Wrong avatar API | Route `.avt` to ImportFile and `.avac` to ImportAVAC; reject APF with AVT before mutation | Routing regression; live import pending |
| 5. Empty turntable result | Validate filename/dimensions and returned artifacts; empty results become MCP errors | Failure regression; CLO API producing images remains unresolved |
| 6. Different default directories | Shared stdlib directory resolver used by plugin, client and harness | Default/override regression |
| 7. Misleading lifecycle/timeout claims | Add stop_bridge, 5-second ping, document shared ownership and non-preemptible native calls | Stop and MCP response regressions; live UI release pending |
| 8. Startup loses fresh requests | Publish session readiness only after initialization; clients wait for it; reject expired/old-session calls | Startup, expiry, old session and abandoned claim regressions |
| 9. Dropped export options | Reject unavailable/unknown options before export, remove option-losing dialog fallbacks, free native option handles on error | Python fallback and native wrapper regressions |
| 10. False mutation success | Check simulation boolean and copy index, use CopyPatternPieceMove for offsets, verify creation count, propagate false API flags as errors | Handler and real MCP error regressions; live semantics pending |
| 11. Windows C symbols not exported | Enable WINDOWS_EXPORT_ALL_SYMBOLS for MSVC | Source configuration fixed; Windows build/load pending |
| 12. Apple build settings in wrong branch | Set the default deployment target before project initialization, respect overrides, use compiler's architecture default | Clean arm64 build; macOS minimum target inspected |

Also corrected the static verifier's evidence claims and default SDK path, stale
export docstrings, unsupported C++ bridge assertions, and tech pack output rules.
Tech pack success now requires newly written, nonempty JSON; a stale existing file
cannot conceal an export that did nothing. Pure Python bridge/shim code is reloaded
on a menu restart; replacing an already loaded native binary can require a CLO restart.

## Offline evidence

- `uv run python -m pytest tests -q`: **38 passed**, including actual MCP stdio
  initialization, discovery of 48 tools, successful ping/stop and propagation of a
  fake CLO simulation failure as an MCP error. No real CLO process is used.
- `uv run python tools/verify_against_clo.py`: **48/48 parameter mappings and 68
  API call sites passed static checks**. This is not proof of live bindings.
- Clean Release shim build with the local CLO 2026.1.224 macOS SDK succeeded.
- Live validation stopped at ping because CLO was closed. No scene mutations
  ran on this branch. Further live testing was deferred at the user's request.

Use the [prepared live checklist](live-test-checklist.md) to complete the remaining
checks. Both the MCP server and CLO bridge must be restarted to use protocol 2.
