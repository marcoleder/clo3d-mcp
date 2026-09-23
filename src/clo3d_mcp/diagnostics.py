"""Local-only support bundles. Never contacts CLO, uploads, or installs crash handlers."""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import stat
import sys
import tempfile
import uuid
import zipfile

from . import __version__
from .ipc import comm_directory

MAX_SCAN_ENTRIES = 10000
CRASH_EXTENSIONS = {".ips", ".crash", ".dmp", ".mdmp", ".wer"}
CLO_NAME = re.compile(r"^(?:appcrash_|apphang_)?clo(?:3d)?(?:[ ._-]|$)", re.IGNORECASE)
BRIDGE_FILES = {"bridge.log", "bridge.log.1", "bridge.log.2", "bridge.log.3",
                "native-session.json", "last-command.json", "ready.json", "scene-review-required.json"}


def _crash_locations(directory):
    if sys.platform == "darwin":
        return [Path.home() / "Library/Logs/DiagnosticReports", Path("/Library/Logs/DiagnosticReports")]
    local = None
    program_data = None
    if sys.platform == "win32":
        local = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData/Local")
        program_data = Path(os.environ.get("ProgramData", "C:/ProgramData"))
    elif str(directory).startswith("/mnt/"):
        # WSL export: use the Windows profile selected by the shared IPC path.
        local = next((p for p in directory.parents
                      if p.name.lower() == "local" and p.parent.name.lower() == "appdata"), None)
        if local is not None:
            program_data = Path(*directory.parts[:3]) / "ProgramData"
    if local is None:
        return []
    return [local / "CrashDumps", local / "Microsoft/Windows/WER/ReportArchive",
            local / "Microsoft/Windows/WER/ReportQueue",
            program_data / "Microsoft/Windows/WER/ReportArchive",
            program_data / "Microsoft/Windows/WER/ReportQueue"]


def _walk(root, warnings, max_depth=4):
    """Bound traversal and never follow directory or file symlinks."""
    if root.is_symlink():
        warnings.append(f"Skipped symlink directory: {root}")
        return
    pending = [(root, 0)]
    visited = 0
    while pending:
        directory, depth = pending.pop()
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    visited += 1
                    if visited > MAX_SCAN_ENTRIES:
                        warnings.append(f"Scan limit reached at {root}; additional files were not collected")
                        return
                    if entry.is_symlink():
                        continue
                    if entry.is_file(follow_symlinks=False):
                        yield Path(entry.path)
                    elif entry.is_dir(follow_symlinks=False) and depth < max_depth:
                        pending.append((Path(entry.path), depth + 1))
        except FileNotFoundError:
            continue
        except OSError as exc:
            warnings.append(f"Cannot scan {directory}: {exc}")


def _read_metadata(path, warnings):
    try:
        if path.is_symlink():
            return {}
        with path.open("rb") as stream:
            data = stream.read(1024 * 1024 + 1)
        if len(data) > 1024 * 1024:
            raise ValueError("metadata exceeds 1 MiB")
        value = json.loads(data)
        if not isinstance(value, dict):
            raise ValueError("metadata is not an object")
        return value
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        warnings.append(f"Cannot read {path}: {exc}")
        return {}


def export_bundle(output_dir=None, crash_directory=None, max_total_mb=512, *, directory=None):
    """Export retained bridge evidence and available CLO crash reports to a ZIP.

    Crashes cannot always produce dumps. Omissions and inaccessible reports are
    listed in the manifest; source files are never deleted or modified.
    """
    if type(max_total_mb) is not int or not 1 <= max_total_mb <= 16384:
        raise ValueError("max_total_mb must be an integer between 1 and 16384")
    directory = Path(directory or comm_directory()).absolute()
    destination = Path(output_dir).expanduser() if output_dir else directory / "diagnostics/exports"
    if not destination.is_absolute():
        raise ValueError("output_dir must be an absolute directory")
    if crash_directory and not Path(crash_directory).expanduser().is_absolute():
        raise ValueError("crash_directory must be an absolute directory")
    destination.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    bundle = destination / f"clo3d-diagnostics-{now:%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:8]}.zip"
    warnings, candidates, seen = [], [], set()
    session = _read_metadata(directory / "native-session.json", warnings)
    command = _read_metadata(directory / "last-command.json", warnings)
    review_required = (directory / "scene-review-required.json").exists()
    findings = []
    if review_required:
        findings.append("Scene review is required after an uncertain operation. Inspect CLO and restore a distinct .zprj backup before further edits.")
    if session and session.get("clean_shutdown") is not True:
        findings.append("The last native session has no clean-shutdown record. It may still be running, or it may have crashed or been terminated; this is not a liveness check.")
    if command and command.get("session") == session.get("session"):
        findings.append(f"Last recorded command: {command.get('command', '(none)')}; stage: {command.get('phase', 'unknown')}; status: {command.get('status', 'not recorded')}.")
        if command.get("message"):
            findings.append("Last command error: " + str(command["message"])[:2048])
    if not findings:
        findings.append("No confirmed failure was found in saved bridge metadata. Include a description of the problem with this bundle.")

    def candidate(source, archive_name, kind):
        if source.is_symlink() or source in seen:
            return
        if source.is_file():
            seen.add(source)
            candidates.append((source, archive_name, kind))

    for name in sorted(BRIDGE_FILES):
        candidate(directory / name, "bridge/" + name, "bridge")
    incidents = directory / "diagnostics/incidents"
    for source in _walk(incidents, warnings, max_depth=1):
        if source.name in BRIDGE_FILES:
            candidate(source, "incidents/" + source.relative_to(incidents).as_posix(), "incident")
    locations = _crash_locations(directory)
    custom = Path(crash_directory).expanduser() if crash_directory else None
    if custom:
        locations.append(custom)
    for index, root in enumerate(locations):
        for source in _walk(root, warnings):
            relative = source.relative_to(root)
            if source.suffix.lower() in CRASH_EXTENSIONS and (root == custom or any(CLO_NAME.match(part) for part in relative.parts)):
                candidate(source, f"crashes/{index}/" + relative.as_posix(), "crash")

    manifest = {
        "format": 1, "created_at": now.isoformat(), "package_version": __version__,
        "system": {"platform": sys.platform, "release": platform.release(),
                   "architecture": platform.machine(), "python": platform.python_version()},
        "comm_directory": str(directory), "searched_crash_locations": [str(p) for p in locations],
        "findings": findings, "warnings": warnings, "included": [], "skipped": [],
        "max_total_mb": max_total_mb, "uploaded": False,
        "privacy": "Bridge logs and OS reports can contain local paths and memory contents. Review the ZIP before manually sharing. Request parameters, response payloads and garment files are not collected.",
    }
    limit, total, crashes = max_total_mb * 1024 * 1024, 0, 0
    temporary = None
    try:
        # mkstemp uses private permissions and an unpredictable name. Publish only
        # after ZIP finalization; a failed export never leaves a plausible final ZIP.
        fd, temporary = tempfile.mkstemp(prefix=".clo3d-diagnostics-", dir=destination)
        with os.fdopen(fd, "w+b") as output:
            with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
                for source, archive_name, kind in candidates:
                    try:
                        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
                        source_fd = os.open(source, flags)
                    except OSError as exc:
                        manifest["skipped"].append({"source": str(source), "reason": str(exc)})
                        continue
                    with os.fdopen(source_fd, "rb") as stream:
                        info = os.fstat(stream.fileno())
                        if not stat.S_ISREG(info.st_mode) or total + info.st_size > limit:
                            manifest["skipped"].append({"source": str(source), "bytes": info.st_size,
                                "reason": "not a regular file or bundle size limit exceeded; source retained"})
                            continue
                        digest, copied = hashlib.sha256(), 0
                        with archive.open(archive_name, "w", force_zip64=True) as entry:
                            # Snapshot at open-time length so growing logs stay bounded.
                            while copied < info.st_size:
                                chunk = stream.read(min(1024 * 1024, info.st_size - copied))
                                if not chunk:
                                    break
                                entry.write(chunk); digest.update(chunk); copied += len(chunk)
                        complete = copied == info.st_size
                        if not complete:
                            warnings.append(f"File changed during collection; incomplete snapshot: {source}")
                        total += copied
                        crashes += int(kind == "crash" and complete)
                        manifest["included"].append({"source": str(source), "archive_path": archive_name,
                            "kind": kind, "bytes": copied, "sha256": digest.hexdigest(), "complete": complete})
                if not crashes:
                    warnings.append("No complete CLO crash report was collected. The OS may not have produced one yet; rerun after a crash report appears or supply crash_directory. Absence of a report does not prove no crash occurred.")
                if sys.platform == "win32" or str(directory).startswith("/mnt/"):
                    warnings.append("Windows LocalDumps is not enabled by default and may not work with an application's own crash reporter. This collector does not change registry settings; see docs/diagnostics.md for local dump setup.")
                if manifest["skipped"]:
                    warnings.append("Some files were omitted; inspect skipped entries in manifest.json. Increase max_total_mb or collect those retained source files separately.")
                manifest["crash_reports"] = crashes
                report = "CLO3D MCP local diagnostics\n\n" + "\n".join(findings)
                report += f"\n\nCrash reports collected: {crashes}\nBridge directory: {directory}\n"
                report += "\n" + "\n".join(warnings)
                report += "\n\nNo data was uploaded. " + manifest["privacy"] + "\n"
                archive.writestr("report.txt", report)
                archive.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
            output.flush(); os.fsync(output.fileno())
        os.replace(temporary, bundle)
        temporary = None
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)
    return {"exported": True, "file_path": str(bundle), "crash_reports": crashes,
            "included_files": len(manifest["included"]), "skipped_files": len(manifest["skipped"]),
            "findings": findings, "warnings": warnings, "uploaded": False,
            "message": "Saved locally. Open report.txt and manifest.json in the ZIP, then share the ZIP manually if desired."}


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description="Export CLO3D MCP diagnostics locally; CLO need not be running.")
    parser.add_argument("--output-dir", help="Destination directory (default: IPC diagnostics/exports)")
    parser.add_argument("--crash-directory", help="Additional dedicated crash-report directory")
    parser.add_argument("--max-total-mb", type=int, default=512, help="Maximum included file bytes in MiB (default: 512)")
    args = parser.parse_args(argv)
    try:
        result = export_bundle(args.output_dir, args.crash_directory, args.max_total_mb)
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        print(f"Could not export diagnostics: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
