# Local diagnostics and crash evidence

Use the **`export_diagnostics`** MCP tool, or run this in the installed checkout:

```sh
uv run --locked clo3d-mcp diagnostics
# Or use the installed entry point directly:
.venv/bin/clo3d-mcp diagnostics --output-dir "$HOME/Desktop/CLO-support"
```

On Windows the entry point is `.venv\Scripts\clo3d-mcp.exe`. The command and tool
work while CLO is stopped, unresponsive, or unable to start. They perform local
file collection only: no bridge command, upload, telemetry, or email is sent.
The result names the ZIP, findings, and missing/skipped evidence. Inside it,
`report.txt` explains the recorded state and `manifest.json` lists sources,
SHA-256 checksums, collection warnings, and the platform/build information.

Default output: `<CLO3D_MCP_DIR>/diagnostics/exports/`, where the directory is
resolved the same way as the MCP client. Use the same explicit override as CLO
if its bridge directory is customized. Each ZIP has a unique filename, so a
new export cannot overwrite an earlier support bundle.

## What is retained

- Native `bridge.log` rotates at **1 MiB**, with **three backups**. Individual
  messages are bounded. Routine successful-command timing logs are off; set
  `CLO3D_MCP_DEBUG=1` in **CLO's environment** before launch to enable them.
  Startup, shutdown and errors remain logged, with each write flushed/closed.
- `native-session.json` records the process, session, Qt/OS, build manifest,
  plugin path and clean-shutdown status. `last-command.json` is replaced
  atomically before SDK dispatch and after it returns, with command name/id,
  stage and error status. It excludes command parameters and result payloads.
  `sdk_returned` does not mean the IPC response was published successfully.
- Before restarting an unclean native session, its metadata and retained logs
  are copied to `diagnostics/incidents/<unique-id>/`. These incident directories
  are never automatically deleted; remove them manually after saving the
  evidence you need. Failure to archive keeps the previous metadata intact
  and logs a collection error instead of blocking CLO or creating scene review.
- The ZIP includes current bridge logs/rotations, session metadata, preserved
  incidents, readiness/review metadata, and available CLO OS crash reports.
  It never copies IPC request/response files or garment/project files.

Logs and OS dumps can contain local file paths or memory contents. Inspect the
ZIP before sending it manually. The collector does not claim that a ZIP is
anonymized, or that the last recorded command proves the crash's cause.

## OS crash reports

A fatal native access violation, segmentation fault, or abort can terminate
CLO. C++ exception handling does not contain those failures. Python exceptions
are usually contained, but Python calling a faulty native SDK can also crash
the host. This plugin leaves CLO's and the OS's crash handlers in place; it
does not try to continue a corrupted process.

On macOS the collector looks in `~/Library/Logs/DiagnosticReports` and
`/Library/Logs/DiagnosticReports` for CLO `.ips`/`.crash` reports. Reports can
appear after the process has exited: export again if the first bundle says
none was found. Apple documents [obtaining OS crash reports](https://developer.apple.com/documentation/xcode/acquiring-crash-reports-and-diagnostic-logs)
and the [IPS format](https://developer.apple.com/documentation/xcode/interpreting-the-json-format-of-a-crash-report).

On Windows the collector checks `%LOCALAPPDATA%/CrashDumps` and the per-user
and `%ProgramData%` WER `ReportQueue`/`ReportArchive` directories. WSL derives
the Windows profile from a detected Windows IPC path. Only CLO-named reports
and CLO WER folders are selected in shared system directories. Supply an
additional dedicated directory for a vendor crash reporter or custom location:

```sh
clo3d-mcp diagnostics --crash-directory /absolute/path/to/crash-reports --max-total-mb 1024
```

Windows **LocalDumps is not enabled by default**, requires administrator
configuration, and may not support applications with their own crash reporter.
An administrator can configure the following **per-application** key using the
actual CLO executable filename from `native-session.json`:

```text
HKLM\SOFTWARE\Microsoft\Windows\Windows Error Reporting\LocalDumps\<CLO executable filename>
  DumpType  REG_DWORD  1   (minidump)
  DumpCount REG_DWORD  10
```

The default dump folder is `%LOCALAPPDATA%\CrashDumps`. The collector does not
change the registry or global crash-reporting policy. See Microsoft's
[LocalDumps setup and limitations](https://learn.microsoft.com/en-us/windows/win32/wer/collecting-user-mode-dumps).

No in-process logger can guarantee evidence for every failure: forced kills,
power loss, inaccessible/full disks and missing OS reports can leave gaps.
The manifest makes missing evidence explicit. A session lacking a clean stop
may also still be running; it is not itself proof of a crash or hang.

Collection is bounded to **512 MiB of source files** by default, configurable
from 1 to 16384 MiB. Oversized files remain at their original paths and are
listed as skipped rather than silently truncated. Symlinks are not followed;
directory scans have a 10,000-entry limit per root. Original files are never
deleted by export, and a failed export removes its partial ZIP.

## Release symbols

Native Release builds retain debug information while keeping optimization:
macOS generates a matching `.dSYM`; MSVC generates a `.pdb`. Keep the binary,
its `.json` checksum manifest, and matching symbols for **every distributed
build**. The user's session record includes the manifest so maintainers can
identify the matching binary. Symbols stay with the maintainer; they are not
copied into customer support ZIPs automatically. A stack trace without the
matching build's symbols may not identify a source line.

## Verification

Offline tests exercise rotation and rotation failure, session preservation,
forced termination of the native test harness, after-exit collection, selective
crash discovery, checksums, size limits, symlinks, unreadable files, failed ZIP
publication, CLI use without importing the MCP server, and the local MCP tool
without any CLO connection. Crash cases are injected into the test harness,
not into a user's CLO session. Windows dump generation and collection from
older CLO crash reporters still need qualification on those hosts.

The [guided native live runs](validation/native-diagnostics-live-2026-09-23.json)
also exercised the local MCP exporter after bridge shutdown and the CLI exporter
with the bridge stopped. ZIP integrity and every included file's checksum passed;
session metadata recorded clean shutdown and the correct Release binary. No crash
was induced in CLO, and no OS crash reports were available during these runs.
