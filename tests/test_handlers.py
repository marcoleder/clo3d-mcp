import json
from types import SimpleNamespace

import pytest


def test_copy_uses_offsets_and_returns_index(plugin):
    calls = []
    plugin.pattern_api.CopyPatternPieceMove = lambda *args: calls.append(args) or 7
    result = plugin.handle_copy_pattern({"pattern_index": 2, "x": 10, "y": -20})
    assert calls == [(2, 10.0, -20.0)]
    assert result["new_index"] == 7
    plugin.pattern_api.CopyPatternPieceMove = lambda *args: -1
    with pytest.raises(RuntimeError, match="failed"):
        plugin.handle_copy_pattern({"pattern_index": 2})


def test_failed_simulation_is_an_error(plugin):
    plugin.utility_api.Simulate = lambda steps: False
    response = json.loads(plugin.process_command(json.dumps({"id": "test", "type": "simulate"})))
    assert response["status"] == "error"


def test_false_import_result_is_an_error(plugin):
    plugin.import_api.ImportFile = lambda path: False
    response = json.loads(plugin.process_command(json.dumps(
        {"id": "test", "type": "import_file", "params": {"file_path": "x.zprj"}})))
    assert response["status"] == "error"


def test_avatar_routes_by_format_and_rejects_unsupported_pose_first(plugin, monkeypatch):
    calls = []
    count = [1]
    def add_avatar(path):
        calls.append(("avt", path))
        count[0] += 1
        return True
    monkeypatch.setattr(plugin, "_shim", lambda: SimpleNamespace(import_avatar=add_avatar))
    plugin.export_api.GetAvatarCount = lambda: count[0]
    plugin.pattern_api.GetPatternCount = lambda: 14
    plugin.import_api.ImportFile = lambda path: pytest.fail("must not replace the garment")
    plugin.import_api.ImportAVAC = lambda *args: calls.append(("avac", *args)) or True
    assert plugin.handle_import_avatar({"file_path": "avatar.AVT"})["imported"]
    assert plugin.handle_import_avatar({"file_path": "a.avac", "apf_path": "p.apf"})["imported"]
    with pytest.raises(ValueError, match="only for .avac"):
        plugin.handle_import_avatar({"file_path": "a.avt", "apf_path": "p.apf"})
    assert calls == [("avt", "avatar.AVT"), ("avac", "a.avac", "p.apf")]


def test_avatar_without_shim_never_falls_back_to_open_project(plugin):
    plugin.import_api.ImportFile = lambda path: pytest.fail("unsafe fallback")
    with pytest.raises(RuntimeError, match="updated native shim"):
        plugin.handle_import_avatar({"file_path": "avatar.avt"})


def test_avatar_true_return_without_state_change_is_failure(plugin, monkeypatch):
    monkeypatch.setattr(plugin, "_shim", lambda: SimpleNamespace(import_avatar=lambda path: True))
    plugin.export_api.GetAvatarCount = lambda: 1
    plugin.pattern_api.GetPatternCount = lambda: 14
    with pytest.raises(RuntimeError, match="did not add"):
        plugin.handle_import_avatar({"file_path": "avatar.avt"})


@pytest.mark.parametrize("format", ["obj", "fbx", "glb", "gltf"])
def test_options_never_silently_fall_back_to_dialog(plugin, format):
    plugin.export_api.ExportGLBWithDialog = lambda *_: pytest.fail("options discarded")
    plugin.export_api.ExportGLTFWithDialog = lambda *_: pytest.fail("options discarded")
    with pytest.raises(RuntimeError, match="does not expose"):
        getattr(plugin, "handle_export_" + format)({"file_path": "x." + format,
                                                  "options": {"bExportAvatar": False}})


def test_python_options_reject_unknown_keys(plugin):
    plugin.export_api.ImportExportOption = lambda: SimpleNamespace(scale=1)
    with pytest.raises(ValueError, match="Unsupported"):
        plugin._build_export_option({"typo": True})


def test_turntable_empty_result_is_failure(plugin):
    calls = []
    plugin.utility_api.GetCurrentColorwayIndex = lambda: 2
    plugin.export_api.ExportTurntableImagesByColorwayIndex = lambda *args: calls.append(args) or []
    with pytest.raises(RuntimeError, match="no images"):
        plugin.handle_export_turntable({"file_path": "view.png"})
    assert calls == [("view.png", 36, 2, 2500, 2500)]


def test_techpack_void_return_requires_artifact(plugin, tmp_path):
    plugin.export_api.ExportTechpackOption = SimpleNamespace
    plugin.export_api.ExportTechPack = lambda *args: None
    with pytest.raises(FileNotFoundError):
        plugin.handle_export_tech_pack({"file_path": str(tmp_path / "pack.json")})


def test_snapshot_flattens_colorway_groups(plugin):
    plugin.export_api.ExportSnapshot3D = lambda path: [["front.png", "back.png"], ["other.png"]]
    assert plugin.handle_export_snapshot({"file_path": "snapshot.png"}) == {
        "exported": True, "file_paths": ["front.png", "back.png", "other.png"]}


def test_fabric_count_and_list_include_unused_fabrics(plugin):
    plugin.fabric_api.GetFabricCount = lambda current=True: 2 if current else 3
    plugin.fabric_api.GetFabricName = lambda index: ["used-a", "used-b", "unused"][index]
    assert plugin.handle_get_fabric_count({}) == {"count": 3}
    assert plugin.handle_get_fabric_list({})["fabrics"][-1] == {"index": 2, "name": "unused"}
