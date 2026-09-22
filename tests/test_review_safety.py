"""Regressions for cancelled opens and partially applied native operations."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from clo3d_mcp.connection import CLO3DOperationUncertain


def request(plugin, command, **params):
    return json.loads(plugin.process_command(json.dumps({"id": "probe", "type": command, "params": params})))


@pytest.mark.parametrize("command", ["open_file", "import_file"])
def test_cancelled_project_open_cannot_claim_success(plugin, tmp_path, command):
    source = tmp_path / "copy.zprj"
    source.write_text("fixture")
    plugin.utility_api.GetProjectFilePath = lambda: str(tmp_path / "original.zprj")
    plugin.import_api.ImportFile = lambda path: True  # Actual cancelled-dialog behavior.
    result = request(plugin, command, file_path=str(source))
    assert result["status"] == "error"
    assert result["outcome"] == "unknown" and result["retry_safe"] is False
    assert "not active" in result["message"]


def test_already_active_project_is_noop_not_unverifiable_reload(plugin, tmp_path):
    source = tmp_path / "active.zprj"
    source.write_text("fixture")
    plugin.utility_api.GetProjectFilePath = lambda: str(source)
    plugin.import_api.ImportFile = lambda path: pytest.fail("must preserve unsaved edits")
    result = request(plugin, "open_file", file_path=str(source))
    assert result["result"]["already_active"] is True


def avatar_scene(plugin):
    state = {"avatars": 1, "patterns": ["bodice", "sleeve"], "project": "original.zprj"}
    plugin.export_api.GetAvatarCount = lambda: state["avatars"]
    plugin.pattern_api.GetPatternCount = lambda: len(state["patterns"])
    plugin.pattern_api.GetPatternPieceName = lambda index: state["patterns"][index]
    plugin.utility_api.GetProjectFilePath = lambda: state["project"]
    return state


@pytest.mark.parametrize("extension", ["avt", "avac"])
@pytest.mark.parametrize("failure", ["false", "true_noop", "pattern_change", "project_change", "exception"])
def test_avatar_failures_are_explicitly_unsafe_to_retry(plugin, monkeypatch, extension, failure):
    state = avatar_scene(plugin)
    calls = []
    def native(*args):
        calls.append(args)
        if failure == "false":
            return False
        if failure == "true_noop":
            return True
        state["avatars"] += 1
        if failure == "pattern_change":
            state["patterns"].pop()
        elif failure == "project_change":
            state["project"] = "unexpected.zprj"
        else:
            raise RuntimeError("native import error after mutation")
        return True
    monkeypatch.setattr(plugin, "_shim", lambda: SimpleNamespace(abi=2, import_avatar=native))
    plugin.import_api.ImportAVAC = native
    first = request(plugin, "import_avatar", file_path="avatar." + extension)
    second = request(plugin, "import_avatar", file_path="avatar." + extension)
    assert first["outcome"] == second["outcome"] == "unknown"
    assert first["scene_review_required"] and not first["retry_safe"]
    assert len(calls) == 1
    assert request(plugin, "get_pattern_count")["status"] == "success"
    assert request(plugin, "stop_bridge")["status"] == "success"


def test_abi1_avatar_rejected_before_any_native_call(plugin, monkeypatch):
    monkeypatch.setattr(plugin, "_shim", lambda: SimpleNamespace(
        abi=1, import_avatar=lambda path: pytest.fail("ABI 1 cannot import")))
    plugin.import_api.ImportFile = lambda path: pytest.fail("unsafe fallback")
    result = request(plugin, "import_avatar", file_path="avatar.avt")
    assert "ABI 2" in result["message"]
    assert "outcome" not in result  # Preflight failure; native code never ran.
    assert not plugin._review_required()


def test_unknown_outcome_survives_new_client_and_requires_verified_recovery(bridge, monkeypatch, tmp_path):
    plugin, connection = bridge
    state = avatar_scene(plugin)
    count = []
    def native(path):
        count.append(path)
        state["avatars"] += 1
        state["patterns"].pop()
        return True
    monkeypatch.setattr(plugin, "_shim", lambda: SimpleNamespace(abi=2, import_avatar=native))
    with pytest.raises(CLO3DOperationUncertain, match="do not retry"):
        connection.send_command("import_avatar", {"file_path": "avatar.avt"})
    from clo3d_mcp.connection import CLO3DConnection
    other = CLO3DConnection(plugin.COMM_DIR)
    with pytest.raises(CLO3DOperationUncertain):
        other.send_command("import_avatar", {"file_path": "avatar.avt"})
    assert len(count) == 1
    assert Path(plugin._review_file()).is_file()
    backup = tmp_path / "backup.zprj"
    backup.write_text("saved scene fixture")
    plugin.import_api.ImportFile = lambda path: True
    with pytest.raises(CLO3DOperationUncertain):
        other.send_command("open_file", {"file_path": str(backup)})
    assert plugin._review_required()  # Cancelled recovery must not unlock mutations.
    def restore(path):
        state["project"] = path
        state["patterns"] = ["bodice", "sleeve"]
        state["avatars"] = 1
        return True
    plugin.import_api.ImportFile = restore
    assert other.send_command("open_file", {"file_path": str(backup)})["verified"]
    assert not plugin._review_required()


@pytest.mark.parametrize("command", ["add_fabric", "import_fabric"])
@pytest.mark.parametrize("returned,after", [(0, 2), (-1, 2), (4294967295, 3), (False, 3)])
def test_fabric_import_failure_cannot_claim_success(plugin, command, returned, after):
    counts = iter([2, after])
    plugin.fabric_api.GetFabricCount = lambda selector: next(counts)
    plugin.fabric_api.AddFabric = lambda path: returned
    result = request(plugin, command, file_path="fabric.zfab")
    assert result["outcome"] == "unknown"
    assert result["status"] == "error"


@pytest.mark.parametrize("command", ["add_fabric", "import_fabric"])
def test_fabric_import_verifies_new_index_and_count(plugin, command):
    counts = iter([2, 3])
    plugin.fabric_api.GetFabricCount = lambda selector: next(counts)
    plugin.fabric_api.AddFabric = lambda path: 2
    result = request(plugin, command, file_path="fabric.zfab")
    assert result["result"]["fabric_index"] == 2


def test_color_setter_checks_sdk_boolean(plugin):
    plugin.fabric_api.SetFabricPBRMaterialBaseColor = lambda *args: False
    result = request(plugin, "set_fabric_color", fabric_index=0)
    assert result["status"] == "error"
    assert "returned false" in result["message"]


def test_generic_import_true_without_change_is_uncertain(plugin, monkeypatch, tmp_path):
    source = tmp_path / "mesh.obj"
    source.write_text("fixture")
    plugin.utility_api.GetProjectFilePath = lambda: "original.zprj"
    monkeypatch.setattr(plugin, "_scene_signature", lambda: {"patterns": ["bodice"]})
    plugin.import_api.ImportFile = lambda path: True
    result = request(plugin, "import_file", file_path=str(source))
    assert result["outcome"] == "unknown"
    assert "without an observable scene change" in result["message"]


@pytest.mark.parametrize("command", ["open_file", "import_file"])
def test_generic_avatar_entrypoints_use_verified_add_route(plugin, monkeypatch, tmp_path, command):
    source = tmp_path / "avatar.avt"
    source.write_text("fixture")
    state = avatar_scene(plugin)
    def add(path):
        state["avatars"] += 1
        return True
    monkeypatch.setattr(plugin, "_shim", lambda: SimpleNamespace(abi=2, import_avatar=add))
    plugin.import_api.ImportFile = lambda path: pytest.fail("generic avatar import is unsafe")
    assert request(plugin, command, file_path=str(source))["status"] == "success"
    assert state["avatars"] == 2
