# Native CLO bridge (opt-in)

The native backend implements the same 48 MCP tools and protocol 3 as the Python
bridge. Start returns immediately; a 50 ms Qt timer processes at most one command
per tick on CLO's application thread. Long SDK calls still block that thread.
The Python backend and ABI-2 shim remain available for rollback.

## Build

Use the full **CLO SDK 2026.1.224**, **Qt 6.10.3**, a matching architecture and
**Release** configuration. The bundled `sdk/` headers alone cannot link a plugin.
The Qt version is enforced at configuration and runtime. The native plugin uses
Core, Gui (image validation), and Widgets (modal-dialog detection).

```sh
cmake -S cpp -B cpp/build-native \
  -DCMAKE_BUILD_TYPE=Release \
  -DCLO_BUILD_NATIVE_PLUGIN=ON \
  -DCLO_BUILD_NATIVE_TESTS=ON \
  -DCLO_SDK_DIR=/path/to/CLO_SDK_v2026.1.224_Mac \
  -DCMAKE_PREFIX_PATH=/path/to/Qt/6.10.3/macos
cmake --build cpp/build-native --config Release -j 8
ctest --test-dir cpp/build-native -C Release --output-on-failure
CLO_NATIVE_HARNESS="$PWD/cpp/build-native/clo_queue_harness" uv run pytest tests/ -q
```

macOS produces `libclo_mcp_plugin_v1.dylib`, a checksum/version manifest beside
it, and `NOTICE`/`LICENSE`. Its load commands resolve CLOAPIInterface and Qt to
CLO's existing frameworks; the build signs the retargeted binary ad hoc. Do not
bundle another Qt or CLO runtime. The deployment target defaults to macOS 15.0.
Release builds also retain matching `.dSYM` (macOS) or `.pdb` (MSVC) symbols for
crash analysis. Archive those alongside the binary and manifest for each release.

Windows uses matching x64 Qt/MSVC `/MD` and a Release build. The plugin exports
the SDK's C entry points explicitly. Windows builds, native byte-range locking,
Unicode SDK paths, and WSL interoperability still need Windows qualification.
Set `CLO_NATIVE_HARNESS` to the built `.exe` for client tests.

The old shim-only command is unchanged and still requires no Qt:

```sh
cmake -S cpp -B cpp/build -DCMAKE_BUILD_TYPE=Release -DCLO_SDK_DIR=/path/to/full/sdk
cmake --build cpp/build --config Release
```

Offline native tests can use the bundled headers without any CLO runtime:

```sh
cmake -S cpp -B cpp/build-offline -DCMAKE_BUILD_TYPE=Release \
  -DCLO_BUILD_SHIM=OFF -DCLO_BUILD_NATIVE_TESTS=ON \
  -DCMAKE_PREFIX_PATH=/path/to/Qt/6.10.3/macos
cmake --build cpp/build-offline -j 8
ctest --test-dir cpp/build-offline --output-on-failure
CLO_NATIVE_HARNESS="$PWD/cpp/build-offline/clo_queue_harness" uv run pytest tests/ -q
```

## Install and use

1. Stop any existing bridge using `stop_bridge` or the shared directory's `stop`
   file. Exit CLO before replacing a binary.
2. In CLO, open **Plugins → Plug-in Manager → Add**, select the native binary,
   and name it **MCP Bridge (native C++)**. Preserve the Python fallback entry.
   Let the manager create native registration metadata; do not set `m_SourceType`
   to `script` for a binary.
3. Start the native menu item. Repeated Start is idempotent. Use the same
   `CLO3D_MCP_DIR` in CLO and the existing external Python MCP server, then ping.
   Defaults are `%TEMP%/clo3d_mcp` on Windows and `~/clo3d_mcp` on macOS.
   macOS ignores `TEMP` and `TMPDIR` so MCP stdio filtering cannot change the path.
4. Native ping reports `backend: cpp`, Qt/SDK versions and scene-review state.
   The 48 CLO tools send commands to the native backend; the additional local
   `export_diagnostics` tool exports support evidence without calling CLO.

The plugin retains a process-lifetime library reference. Removing or refreshing
the menu entry cannot unload active timer code; removal does **not** stop the
service. Stop explicitly. A clean application exit stops the timer, removes its
readiness and releases the consumer lock. Never overwrite a loaded binary;
restart CLO for every binary update.

Switch back by stopping native service, then starting the existing Python menu
entry. Both backends honor the same review marker and abandoned claims. A
backend switch does not authorize repeating a timed-out mutation.

## Behavior and limits

- Live preview defaults off. `set_live_preview(true)` requests extra native
  refreshes after mutations, without snapshot exports or preview PNG files.
  Supplying a path explicitly enables snapshot compatibility mode. A no-path
  call resets that mode. Normal CLO repaint continues when preview is off.
- `refresh_view` normally returns `refreshed: true`, `refresh_requested: true`,
  `repainted: false`, `snapshot: null`, `preview_mode: native`. Paint completion
  is unconfirmed; this is not a refresh failure. `export_snapshot` captures an
  image for inspection. Capture failures after successful mutations appear as
  `preview_error`, preserving the successful mutation result.
- Indices are revalidated at dispatch. Integers exclude booleans, fractions,
  negatives and overflow. Point types are 0/2/3; assignment options are 1–3;
  color channels 0–255; face values 0–2. Model and tech-pack options use the
  shim's allowlist and SDK constructor defaults. Axes accept 0–2, weld 0–3.
- An omitted or null simulation mode selects GPU for quality 3 and CPU for
  qualities 0–2. Explicit CPU/GPU modes remain authoritative.
- File arguments require absolute paths and existing input files/output parent
  directories. Exports verify nonempty artifacts, format structure and freshness.
  Use a dedicated output directory: freshness scans reject directories over
  10,000 files before execution. These scans also apply to explicit snapshot
  preview; default native preview skips artifact validation. Message envelopes
  are limited to 16 MiB. Oversized reads return a small error and leave edits
  available. An oversized response after a mutating SDK call returns an error
  stating that the command may have been applied and requires scene review.
- The queue scans at most 64 entries per pass, retains one claim, and never
  waits for acknowledgement in a loop. Ordering is best effort within scan
  windows. Startup recovery and cleanup also run in bounded timer turns.
- Known Qt modal dialogs defer new claims. Deadlines on existing claims still
  expire. The reentrancy guard covers SDK calls, readbacks, artifact checks,
  preview and response publication. Native platform dialogs may require further
  host-specific busy detection.
- An exception or failed postcondition after a mutating SDK call conservatively
  marks the outcome unknown. Reads/session controls stay available; exports and
  further mutations are blocked. Only loading a distinct saved `.zprj` with a
  verified active path clears review. Reloading the active path is a no-op and
  cannot clear review. This is stricter than some Python setter failures.
- Startup and handshake write failures are logged without requiring scene
  review. Failed offers and early rejections retire their unexecuted claims;
  terminal publication failures after dispatch retain unknown-outcome handling.
- No automatic timeout retry, cancellation, rollback, or backend fallback.
  Simulation is one synchronous call; imports/exports may open dialogs.
  Coordinate structural edits with the assistant because indices can shift
  between commands. Camera interaction does not reserve scene objects.

## Logs and support bundles

Native logs rotate at 1 MiB with three backups. Successful-command timing logs
require `CLO3D_MCP_DEBUG=1` in CLO's environment; errors and lifecycle events are
always logged. Atomic last-command/session breadcrumbs remain enabled without
debug logging, and unclean sessions are preserved before a restart overwrites
their metadata. `clo3d-mcp diagnostics` or the local `export_diagnostics` MCP
tool creates a ZIP containing retained logs and available OS crash reports.
No upload occurs. See [diagnostics and crash-report limitations](../docs/diagnostics.md).

Read the [implementation and qualification record](../docs/cpp-plugin-rewrite-plan.md)
before selecting native as your default. Existing Python-only diagnostic commands
return an explicit unsupported-command error on native.
