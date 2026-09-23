import asyncio
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

import pytest

from clo3d_mcp import diagnostics


@pytest.fixture
def evidence(tmp_path, monkeypatch):
    directory = tmp_path / "ipc"
    directory.mkdir()
    crashes = tmp_path / "crashes"
    crashes.mkdir()
    monkeypatch.setenv("CLO3D_MCP_DIR", str(directory))
    monkeypatch.setattr(diagnostics, "_crash_locations", lambda _: [crashes])
    return directory, crashes


def write_json(path, value):
    path.write_text(json.dumps(value))


def test_bundle_collects_only_relevant_evidence_and_checksums(evidence):
    directory, crashes = evidence
    (directory / "bridge.log").write_text("error: failed to publish\n")
    (directory / "bridge.log.1").write_text("older evidence\n")
    write_json(directory / "native-session.json", {"session": "abc", "clean_shutdown": False,
        "build": {"binary_sha256": "build-id"}})
    write_json(directory / "last-command.json", {"session": "abc", "command": "copy_colorway", "phase": "dispatching"})
    write_json(directory / "scene-review-required.json", {"reason": "outcome unknown"})
    (directory / "private.zprj").write_bytes(b"private garment")
    (directory / "requests").mkdir()
    (directory / "requests/private.working").write_text('{"params": "private input"}')
    incident = directory / "diagnostics/incidents/abc"
    incident.mkdir(parents=True)
    (incident / "bridge.log").write_text("preserved crash log\n")
    (incident / "private.zprj").write_bytes(b"private garment")
    (crashes / "CLO-2026-09-23.ips").write_text('{"app_name": "CLO", "note": "袖"}')
    (crashes / "CLO.1234.dmp").write_bytes(b"\0dump\x01")
    wer = crashes / "AppCrash_CLO.exe_1234"
    wer.mkdir()
    (wer / "Report.wer").write_text("AppName=CLO.exe")
    (crashes / "CloudAgent-2026.ips").write_text("unrelated")
    (crashes / "Safari.crash").write_text("unrelated")
    before = {p: p.read_bytes() for p in directory.rglob("*") if p.is_file()}
    result = diagnostics.export_bundle()
    assert result["exported"] and result["crash_reports"] == 3 and result["uploaded"] is False
    assert "Scene review is required" in result["findings"][0]
    assert any("copy_colorway" in finding for finding in result["findings"])
    with zipfile.ZipFile(result["file_path"]) as archive:
        assert archive.testzip() is None
        manifest = json.loads(archive.read("manifest.json"))
        assert not manifest["uploaded"] and not manifest["skipped"]
        for item in manifest["included"]:
            data = archive.read(item["archive_path"])
            assert hashlib.sha256(data).hexdigest() == item["sha256"]
            assert len(data) == item["bytes"] and item["complete"]
        assert not any("private" in name or "Safari" in name or "CloudAgent" in name for name in archive.namelist())
        assert "No data was uploaded" in archive.read("report.txt").decode()
    assert all(path.read_bytes() == content for path, content in before.items())
    if os.name != "nt":
        assert Path(result["file_path"]).stat().st_mode & 0o077 == 0


def test_no_dump_and_oversized_dump_are_explicit_not_silently_truncated(evidence):
    directory, crashes = evidence
    dump = crashes / "CLO.1.dmp"
    dump.write_bytes(b"x" * (1024 * 1024 + 1))
    result = diagnostics.export_bundle(max_total_mb=1)
    assert result["crash_reports"] == 0 and result["skipped_files"] == 1
    assert any("No complete CLO crash report" in warning for warning in result["warnings"])
    with zipfile.ZipFile(result["file_path"]) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["skipped"][0]["source"] == str(dump)
        assert not any(name.endswith(".dmp") for name in archive.namelist())
    assert dump.stat().st_size == 1024 * 1024 + 1


def test_malformed_metadata_and_unreadable_report_do_not_block_other_logs(evidence, monkeypatch):
    directory, crashes = evidence
    (directory / "bridge.log").write_text("retained error")
    (directory / "native-session.json").write_text("{broken")
    blocked = crashes / "CLO.ips"
    blocked.write_text("report")
    original_open = diagnostics.os.open
    def open_file(path, *args, **kwargs):
        if Path(path) == blocked:
            raise PermissionError("report locked")
        return original_open(path, *args, **kwargs)
    monkeypatch.setattr(diagnostics.os, "open", open_file)
    result = diagnostics.export_bundle()
    assert result["included_files"] == 2 and result["skipped_files"] == 1
    assert any("Cannot read" in warning for warning in result["warnings"])


def test_symlink_reports_and_incident_files_are_not_followed(evidence, tmp_path):
    directory, crashes = evidence
    secret = tmp_path / "secret.txt"
    secret.write_text("do not collect")
    try:
        (crashes / "CLO.ips").symlink_to(secret)
        (directory / "bridge.log").symlink_to(secret)
    except OSError:
        pytest.skip("symlink creation unavailable")
    result = diagnostics.export_bundle()
    assert result["included_files"] == 0


def test_failed_publication_leaves_no_partial_final_zip(evidence, monkeypatch):
    directory, _ = evidence
    def fail(*args):
        raise OSError("disk full")
    monkeypatch.setattr(diagnostics.os, "replace", fail)
    with pytest.raises(OSError, match="disk full"):
        diagnostics.export_bundle()
    assert list((directory / "diagnostics/exports").iterdir()) == []


@pytest.mark.parametrize("value", [0, -1, 16385, True, 1.5])
def test_invalid_bundle_limits_are_rejected(evidence, value):
    with pytest.raises(ValueError, match="max_total_mb"):
        diagnostics.export_bundle(max_total_mb=value)


def test_custom_crash_directory_and_output_are_supported(evidence, tmp_path):
    custom = tmp_path / "vendor-reports"
    custom.mkdir()
    (custom / "crash.dmp").write_bytes(b"vendor dump")
    output = tmp_path / "support"
    first = diagnostics.export_bundle(str(output), str(custom))
    second = diagnostics.export_bundle(str(output), str(custom))
    assert first["crash_reports"] == 1
    assert Path(first["file_path"]).parent == output and first["file_path"] != second["file_path"]
    with pytest.raises(ValueError, match="absolute"):
        diagnostics.export_bundle("relative")


def test_scan_limit_is_reported(evidence, monkeypatch):
    _, crashes = evidence
    for number in range(3):
        (crashes / f"CLO-{number}.ips").write_text("report")
    monkeypatch.setattr(diagnostics, "MAX_SCAN_ENTRIES", 1)
    result = diagnostics.export_bundle()
    assert result["crash_reports"] == 1
    assert any("Scan limit reached" in warning for warning in result["warnings"])


def test_local_mcp_tool_works_without_connecting_to_clo(evidence, monkeypatch):
    from clo3d_mcp import server
    monkeypatch.setattr(server, "get_connection", lambda: pytest.fail("diagnostics contacted CLO"))
    content = asyncio.run(server.mcp.call_tool("export_diagnostics", {}))
    structured = json.loads(content[0].text)
    assert structured["exported"] and Path(structured["file_path"]).is_file()


def test_cli_works_without_importing_mcp_server(evidence, tmp_path):
    result = subprocess.run([sys.executable, "-c",
        "import sys; from clo3d_mcp import diagnostics; diagnostics._crash_locations = lambda _: []; "
        "sys.modules['clo3d_mcp.server'] = None; from clo3d_mcp import main; main()",
        "diagnostics", "--output-dir", str(tmp_path / "support")],
        capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    response = json.loads(result.stdout)
    assert Path(response["file_path"]).is_file() and response["uploaded"] is False


def test_windows_and_wsl_crash_locations(monkeypatch):
    monkeypatch.setattr(diagnostics.sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", "/users/test/AppData/Local")
    monkeypatch.setenv("ProgramData", "/ProgramData")
    locations = diagnostics._crash_locations(Path("/ipc"))
    assert Path("/users/test/AppData/Local/CrashDumps") in locations
    assert Path("/ProgramData/Microsoft/Windows/WER/ReportQueue") in locations
    monkeypatch.setattr(diagnostics.sys, "platform", "linux")
    locations = diagnostics._crash_locations(Path("/mnt/c/Users/test/AppData/Local/Temp/clo3d_mcp"))
    assert Path("/mnt/c/Users/test/AppData/Local/CrashDumps") in locations
    assert Path("/mnt/c/ProgramData/Microsoft/Windows/WER/ReportArchive") in locations
