# Pre-merge review follow-up

Reviewed the reported Python and connection issues against `feat/native-cpp-plugin`
after the native queue fixes. Several reports referred to code already replaced
by the correctness audit merged into the branch's base. This follow-up fixes the
remaining defaults and compatibility gaps and strengthens executable coverage.

| Finding | Current resolution and evidence |
|---|---|
| macOS stdio strips `TMPDIR` | Both backends and the client use `~/clo3d_mcp` on macOS. This update also ignores `TEMP` there. A subprocess test uses the MCP SDK's actual filtered environment and verifies the same path as CLO's shared Python resolver. Native tests check its matching rule. |
| Export option construction errors discard options | Already fixed: no export-without-options exception fallback remains. New tests inject both `AttributeError` and `TypeError` into constructors for OBJ, FBX, GLB and glTF and verify no export occurs. |
| Delete/copy replay after timeout | Already fixed: one request publication, one acknowledgement, no resend. New tests call the actual server tools through the Python bridge, time out inside each SDK call, and verify exactly one mutation. Native nonreplay coverage remains in place. |
| Tech pack always reports success | Already fixed: verify freshly written, nonempty JSON; missing artifacts and unchanged existing files raise errors. Tests cover both Python and shim paths. |
| Ping takes minutes | Already fixed: the default deadline is five seconds. New tests exercise the server's default ping with absent and stale readiness and check the total deadline and publication count. |
| Avatar format mismatch | Already fixed: `.avt` uses native add mode (shim ABI 2 for Python); `.avac` uses `ImportAVAC`. Tool documentation and routing tests cover both, including pose restrictions. |
| Stale `uv.lock` | Not reproduced: `uv sync --locked` succeeds without modifying the lockfile. No dependency changes are needed. |
| Server-only environment override | The resolver docstring and README explicitly require setting `CLO3D_MCP_DIR` in both processes. |
| Older one-argument APIs | The Python fallback now selects discoverable one-argument `SetSimulationQuality` and `CopyColorway` bindings before SDK entry. Nondefault options requiring the second argument are rejected. Signature and pybind docstring tests cover both arities; a runtime `TypeError` never triggers a second call. |
| GPU preset defaults to CPU | Fixed in the server and both handlers: omitted/null mode chooses GPU for quality 3, otherwise CPU. Explicit integer modes are honored. The schema fixture changes only this optional parameter's default/null acceptance. |
| `TMPDIR` overrides Windows/WSL | Windows explicitly uses `TEMP`; WSL probes Windows user directories before falling back to home. Tests set conflicting temp variables and verify precedence, including explicit overrides. |
| Unknown export option keys ignored | Already fixed: Python option objects, the shim and native option builders reject unsupported keys; existing tests cover all three paths. |
| Duplicated OBJ option construction | Already fixed: OBJ shares `_build_export_option` with the other model exports; shim exports share their native option builder. |
| Duplicated fabric import | Already fixed: Python add/import share `_add_fabric`; native add/import share `addFabric`, including postconditions. |
| Outdated tool count and missing handler coverage | README lists 48 tools and now states platform-specific path rules precisely. Schema and executable Python tool-to-handler checks always run; the native registry comparison runs with native tests enabled. |

Validation for this follow-up:

- `uv sync --locked`: passed; lockfile unchanged.
- `CLO_NATIVE_HARNESS="$PWD/cpp/build-offline/clo_queue_harness" uv run --locked pytest tests/ -q`: **173 passed**.
- Offline native build and CTest: **3/3 suites passed**, including simulation defaults and directory selection.
- Release plugin build against CLO SDK 2026.1.224 / Qt 6.10.3: passed in the separate `cpp/build-review-fixes` directory.
- Static SDK verifier: **48/48 parameter mappings**, **84 current API call sites** passed. It explicitly skips the two guarded legacy arities because the checked-in SDK defines the current signatures.

The earlier live qualification remains recorded in
[`cpp-plugin-rewrite-plan.md`](cpp-plugin-rewrite-plan.md). This follow-up did
not reload CLO or modify the live scene. Older CLO binaries and Windows/WSL
hosts were not available for live revalidation: legacy compatibility is limited
to discoverable signatures, and the native plugin still requires its matching
2026.1 SDK and Qt runtime.
