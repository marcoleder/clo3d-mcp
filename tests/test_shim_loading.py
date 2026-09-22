"""Discovery must prefer usable ABI 2 and recover from transient load failures."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def shim_module(monkeypatch):
    monkeypatch.delenv("CLO_SHIM_PATH", raising=False)
    path = Path(__file__).resolve().parents[1] / "plugin/clo_shim.py"
    spec = importlib.util.spec_from_file_location("shim_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def candidates(module, monkeypatch, tmp_path, versions):
    paths = []
    libraries = {}
    for index, version in enumerate(versions):
        path = str(tmp_path / str(index))
        Path(path).touch()
        paths.append(path)
        libraries[path] = SimpleNamespace(path=path, abi=version, ready=True)
    monkeypatch.setattr(module, "_candidate_paths", lambda: paths)
    monkeypatch.setattr(module, "CloShim", libraries.__getitem__)
    return libraries, paths


def test_later_abi2_wins_over_earlier_abi1(shim_module, monkeypatch, tmp_path):
    libs, paths = candidates(shim_module, monkeypatch, tmp_path, [1, 2])
    assert shim_module.load() is libs[paths[1]]
    assert shim_module.status()["path"] == paths[1]


def test_unready_abi2_is_retried_after_abi1_was_cached(shim_module, monkeypatch, tmp_path):
    libs, paths = candidates(shim_module, monkeypatch, tmp_path, [2, 1])
    libs[paths[0]].ready = False
    assert shim_module.load().abi == 1
    libs[paths[0]].ready = True
    assert shim_module.load().abi == 2


def test_explicit_path_does_not_silently_select_another_library(shim_module, monkeypatch, tmp_path):
    libs, paths = candidates(shim_module, monkeypatch, tmp_path, [1, 2])
    assert shim_module.load().abi == 2
    monkeypatch.setenv("CLO_SHIM_PATH", paths[0])
    assert shim_module.load() is libs[paths[0]]


def test_failed_load_is_not_cached_forever(shim_module, monkeypatch, tmp_path):
    libs, paths = candidates(shim_module, monkeypatch, tmp_path, [2])
    def fail(path):
        raise OSError("library still being installed")
    monkeypatch.setattr(shim_module, "CloShim", fail)
    assert shim_module.load() is None
    assert "still being installed" in shim_module.status()["errors"][0]["error"]
    monkeypatch.setattr(shim_module, "CloShim", libs.__getitem__)
    assert shim_module.load() is libs[paths[0]]


@pytest.mark.parametrize("abi", [0, 3])
def test_unknown_abi_rejected_before_binding_exports(shim_module, monkeypatch, abi):
    lib = SimpleNamespace(clo_shim_abi_version=lambda: abi, clo_shim_ready=lambda: 1)
    monkeypatch.setattr(shim_module.ctypes, "CDLL", lambda path: lib)
    with pytest.raises(RuntimeError, match="Unsupported.*ABI"):
        shim_module.CloShim("test-library")


def test_abi2_missing_avatar_symbol_is_rejected(shim_module, monkeypatch):
    lib = SimpleNamespace(clo_shim_abi_version=lambda: 2, clo_shim_ready=lambda: 1)
    monkeypatch.setattr(shim_module.ctypes, "CDLL", lambda path: lib)
    with pytest.raises(RuntimeError, match="missing clo_import_avatar"):
        shim_module.CloShim("test-library")


@pytest.mark.parametrize("code", [0, -1, -2])
def test_native_avatar_failure_codes_propagate_to_uncertain_response(shim_module, plugin, monkeypatch, code):
    import json
    shim = shim_module.CloShim.__new__(shim_module.CloShim)
    shim._abi = 2
    shim.lib = SimpleNamespace(clo_import_avatar=lambda path: code)
    monkeypatch.setattr(plugin, "_shim", lambda: shim)
    plugin.export_api.GetAvatarCount = lambda: 1
    plugin.pattern_api.GetPatternCount = lambda: 0
    plugin.utility_api.GetProjectFilePath = lambda: "original.zprj"
    response = json.loads(plugin.process_command(json.dumps({
        "id": "failure-code", "type": "import_avatar", "params": {"file_path": "avatar.avt"}})))
    assert response["status"] == "error"
    assert response["outcome"] == "unknown" and response["retry_safe"] is False


@pytest.mark.parametrize("format", ["obj", "fbx", "glb", "gltf"])
def test_native_export_paths_are_returned_without_rejected_option_plumbing(shim_module, plugin, monkeypatch, format):
    shim = shim_module.CloShim.__new__(shim_module.CloShim)
    freed = []
    def export(*args):
        args[-2].value = b"/output/model.mesh"
        return 1
    shim.lib = SimpleNamespace(clo_opts_create=lambda: 123, clo_opts_free=freed.append,
                               clo_opts_set_bool=lambda *args: 1)
    setattr(shim.lib, "clo_export_" + format, export)
    monkeypatch.setattr(plugin, "_shim", lambda: shim)
    result = getattr(plugin, "handle_export_" + format)({
        "file_path": "model." + format, "options": {"bExportAvatar": False}})
    assert result["file_paths"] == ["/output/model.mesh"]
    assert result["exported"] is True
    assert "rejected_options" not in result
    assert freed == [123]


def test_native_techpack_verifies_artifact_without_rejected_options(shim_module, plugin, monkeypatch, tmp_path):
    shim = shim_module.CloShim.__new__(shim_module.CloShim)
    freed = []
    def export(path, handle):
        Path(path.decode()).write_text('{"garment": true}')
        return 0
    shim.lib = SimpleNamespace(clo_tp_opts_create=lambda: 123, clo_tp_opts_free=freed.append,
                               clo_tp_opts_set_bool=lambda *args: 1, clo_export_techpack=export)
    monkeypatch.setattr(plugin, "_shim", lambda: shim)
    result = plugin.handle_export_tech_pack({"file_path": str(tmp_path / "pack.json"),
                                             "options": {"m_bSaveZprj": False}})
    assert result["exported"] is True
    assert "rejected_options" not in result
    assert freed == [123]
