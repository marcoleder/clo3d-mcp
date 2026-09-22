import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
from live_validation import validate_result
from live_test import Server


@pytest.mark.parametrize("flag", ["imported", "exported", "saved", "simulated"])
def test_mcp_success_with_false_api_flag_fails(flag):
    server = Server.__new__(Server)
    server._rpc = lambda *args: {"result": {"content": [
        {"type": "text", "text": json.dumps({flag: False})}]}}
    ok, message = server.call("test")
    assert not ok
    assert flag + "=false" in message


def test_export_requires_actual_artifact(tmp_path):
    with pytest.raises(ValueError, match="Missing or empty"):
        validate_result("export_obj", {"exported": True, "file_path": str(tmp_path / "x.obj")}, {})


def test_gltf_requires_referenced_resources(tmp_path):
    path = tmp_path / "x.gltf"
    path.write_text(json.dumps({"asset": {"version": "2.0"}, "meshes": [{}],
                               "buffers": [{"uri": "missing.bin"}]}))
    with pytest.raises(ValueError, match="Missing glTF resource"):
        validate_result("export_gltf", {"file_path": str(path)}, {})


def test_preparation_does_not_start_mcp_or_clo(monkeypatch):
    import live_test
    monkeypatch.setattr(sys, "argv", ["live_test.py"])
    monkeypatch.setattr(live_test, "Server", lambda: pytest.fail("must not start live testing"))
    assert live_test.main() == 0


def test_create_failure_does_not_claim_success(plugin):
    plugin.pattern_api.GetPatternCount = lambda: 3
    plugin.pattern_api.CreatePatternWithPoints = lambda points: 0
    with pytest.raises(RuntimeError, match="failed"):
        plugin.handle_create_pattern({"points": [[0, 0], [0, 1], [1, 0]]})


def test_existing_techpack_does_not_hide_noop_export(plugin, tmp_path):
    path = tmp_path / "pack.json"
    path.write_text('{"old": true}')
    plugin.export_api.ExportTechpackOption = SimpleNamespace
    plugin.export_api.ExportTechPack = lambda *args: None
    with pytest.raises(RuntimeError, match="did not update"):
        plugin.handle_export_tech_pack({"file_path": str(path)})


def test_native_unknown_option_fails_before_export_and_frees_handle():
    path = TOOLS.parent / "plugin/clo_shim.py"
    spec = importlib.util.spec_from_file_location("test_clo_shim", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    shim = module.CloShim.__new__(module.CloShim)
    freed = []
    shim.lib = SimpleNamespace(clo_opts_create=lambda: 123, clo_opts_free=freed.append)
    with pytest.raises(ValueError, match="Unsupported export option"):
        shim._export(lambda *_: pytest.fail("export executed"), "x.obj", {"typo": True})
    assert freed == [123]


def test_unknown_outcome_aborts_automatic_restore(monkeypatch):
    import live_test
    calls = []
    server = SimpleNamespace(call=lambda *args, **kwargs: calls.append(args), close=lambda: None)
    def interrupted():
        live_test.ACTIVE.update(server=server, connected=True, backup="backup.zprj")
        raise live_test.IndeterminateCommand("CLO is still working")
    monkeypatch.setattr(sys, "argv", ["live_test.py", "--run-live"])
    monkeypatch.setattr(live_test, "exercise", interrupted)
    monkeypatch.setattr(live_test, "_release_bridge", lambda: None)
    assert live_test.main() == 1
    assert calls == []


def test_server_marks_timeout_as_unknown_outcome():
    from live_test import IndeterminateCommand
    server = Server.__new__(Server)
    server._rpc = lambda *args: {"result": {"isError": True, "content": [
        {"type": "text", "text": "Timed out waiting for CLO3D; not retried"}]}}
    with pytest.raises(IndeterminateCommand):
        server.call("copy_pattern")


def test_cancelled_open_aborts_real_harness_before_scene_edits(monkeypatch, tmp_path):
    """An old bridge can claim success; the harness must independently check."""
    import live_test
    calls = []
    src = tmp_path / "source.zprj"
    src.write_text("garment fixture")
    class FakeServer:
        def call(self, name, args=None, timeout=240):
            calls.append(name)
            if name == "get_project_info":
                return True, {"project_path": "original-user-scene.zprj"}
            if name in ("ping", "save_project", "open_file"):
                return True, {}
            if name in ("get_pattern_list", "get_fabric_list", "get_colorways", "get_avatars"):
                return True, {"count": 1}
            pytest.fail("Scene edited after cancelled open: " + name)
        def _rpc(self, *args):
            return {"result": {"tools": []}}
        def close(self):
            pass
    monkeypatch.setattr(live_test, "Server", FakeServer)
    monkeypatch.setattr(live_test, "SERVER_BIN", src)
    monkeypatch.setattr(live_test, "_release_bridge", lambda: None)
    monkeypatch.setattr(sys, "argv", ["live_test.py", str(src), "--run-live"])
    assert live_test.main() == 1
    assert live_test.ACTIVE["uncertain"]
    assert calls.count("open_file") == 1  # No automatic recovery on unknown outcome.
    results = Path(live_test.ACTIVE["backup"]).parent / "results.json"
    assert json.loads(results.read_text())[-1][1] is False


@pytest.mark.parametrize("wrong_path", [True, False])
def test_cleanup_does_not_report_cancelled_or_incorrect_restore_as_success(monkeypatch, wrong_path):
    import live_test
    calls = []
    def call(name, args=None, **kwargs):
        calls.append(name)
        if name == "get_project_info":
            return True, {"project_path": "test-copy.zprj" if wrong_path else "backup.zprj"}
        return True, {}  # Claimed open success, but state differs from baseline.
    server = SimpleNamespace(call=call, close=lambda: None)
    def partial():
        live_test.ACTIVE.update(server=server, connected=True, backup="backup.zprj",
                               original_state={"get_pattern_list": {"count": 7}})
        return 0
    monkeypatch.setattr(sys, "argv", ["live_test.py", "--run-live"])
    monkeypatch.setattr(live_test, "exercise", partial)
    monkeypatch.setattr(live_test, "_release_bridge", lambda: None)
    assert live_test.main() == 1
    assert live_test.ACTIVE["uncertain"]
    assert calls.count("open_file") == 1
    assert "stop_bridge" not in calls
