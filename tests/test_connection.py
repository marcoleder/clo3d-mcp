import concurrent.futures
import json
import multiprocessing
from pathlib import Path
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
import uuid

import pytest

from clo3d_mcp.connection import CLO3DConnection, CLO3DConnectionError
from clo3d_mcp import ipc
from clo3d_mcp.ipc import BridgeQueue, PROTOCOL, atomic_json, bridge_lock, comm_directory, read_json


def _child_call(directory, value):
    return CLO3DConnection(directory).send_command("echo", {"value": value})


def test_ping_and_stop(bridge):
    plugin, connection = bridge
    assert connection.ping()
    assert connection.send_command("stop_bridge") == {"stopped": True}
    assert not connection.connected


def test_handler_error_is_not_replayed(bridge):
    plugin, connection = bridge
    calls = []
    def handler(params):
        calls.append(params)
        raise RuntimeError("failed after mutation")
    plugin.HANDLERS["mutate"] = handler
    with pytest.raises(CLO3DConnectionError, match="failed after mutation"):
        connection.send_command("mutate")
    time.sleep(.15)
    assert len(calls) == 1


def test_timeout_is_not_replayed_and_does_not_steal_next_response(bridge):
    plugin, connection = bridge
    started = threading.Event()
    completed = threading.Event()
    calls = []
    def handler(params):
        calls.append(params)
        started.set()
        time.sleep(.6)
        completed.set()
        return {"done": True}
    plugin.HANDLERS["slow"] = handler
    with pytest.raises(CLO3DConnectionError, match="not retried"):
        connection.send_command("slow", timeout=.4)
    assert started.is_set()
    assert connection.ping()
    assert completed.is_set()
    assert len(calls) == 1


def test_multiple_processes_keep_their_own_responses(bridge):
    plugin, connection = bridge
    plugin.HANDLERS["echo"] = lambda params: params
    with concurrent.futures.ProcessPoolExecutor(
        max_workers=4, mp_context=multiprocessing.get_context("spawn")
    ) as pool:
        jobs = [pool.submit(_child_call, connection.comm_dir, n) for n in range(16)]
        assert [j.result(timeout=10) for j in jobs] == [{"value": n} for n in range(16)]


def test_no_bridge_has_short_bounded_wait(tmp_path):
    start = time.monotonic()
    with pytest.raises(CLO3DConnectionError, match=f"No protocol-{PROTOCOL}"):
        CLO3DConnection(tmp_path).send_command("ping", timeout=.05)
    assert time.monotonic() - start < 1
    assert not list(tmp_path.rglob("*.json"))


def test_client_waits_for_readiness_before_publishing(plugin):
    connection = CLO3DConnection(plugin.COMM_DIR)
    with concurrent.futures.ThreadPoolExecutor() as pool:
        future = pool.submit(connection.send_command, "ping", timeout=2)
        time.sleep(.1)
        assert not list(Path(plugin.COMM_DIR).rglob("requests/*.json"))
        plugin._server_running = True
        thread = threading.Thread(target=plugin.poll_loop)
        thread.start()
        try:
            assert future.result(3)["pong"]
        finally:
            plugin._server_running = False
            thread.join(2)


def request(queue, **overrides):
    value = {"id": uuid.uuid4().hex, "protocol": PROTOCOL, "session": queue.session,
             "type": "ping", "params": {}, "timeout_seconds": 10}
    value.update(overrides)
    atomic_json(queue.requests / (value["id"] + ".json"), value)
    return value


@pytest.mark.parametrize("overrides", [{"timeout_seconds": 0}, {"session": "old"}, {"protocol": 2}])
def test_invalid_or_expired_queued_calls_do_not_execute(tmp_path, overrides):
    queue = BridgeQueue(tmp_path)
    queue.start()
    value = request(queue, **overrides)
    queue.process_one(lambda _: pytest.fail("must not execute"))
    assert read_json(queue.responses / (value["id"] + ".json"))["status"] == "error"


def test_crashed_claim_is_not_replayed_after_restart(tmp_path):
    queue = BridgeQueue(tmp_path)
    queue.start()
    value = request(queue)
    queue.process_one(lambda _: pytest.fail("must await client acknowledgement"))
    offered = read_json(queue.responses / (value["id"] + ".json"))
    atomic_json(queue.requests / (value["id"] + ".ack"), {
        "id": value["id"], "session": queue.session, "token": offered["token"], "timeout_seconds": 10})
    with pytest.raises(RuntimeError):
        queue.process_one(lambda _: (_ for _ in ()).throw(RuntimeError("crash")))
    second = BridgeQueue(tmp_path)
    second.start()
    assert not second.process_one(lambda _: pytest.fail("replayed"))
    # Cleanup retires the claim; its old session still prevents replay.
    atomic_json(second.requests / (value["id"] + ".json"), value)
    assert second.process_one(lambda _: pytest.fail("replayed"))
    assert read_json(second.responses / (value["id"] + ".json"))["status"] == "error"


def test_duplicate_bridge_lock_rejected(tmp_path):
    with bridge_lock(tmp_path):
        with pytest.raises(RuntimeError, match="already serving"):
            with bridge_lock(tmp_path):
                pytest.fail("two consumers")


@pytest.mark.parametrize("platform", ["darwin", "win32"])
def test_defaults_match_plugin(plugin, monkeypatch, platform):
    monkeypatch.delenv("CLO3D_MCP_DIR")
    monkeypatch.setattr(ipc.sys, "platform", platform)
    monkeypatch.setenv("TMPDIR", "/ignored/temp")
    monkeypatch.delenv("TEMP", raising=False)
    assert comm_directory() == str(Path.home() / "clo3d_mcp")
    monkeypatch.setenv("TEMP", "/some/temp")
    expected = Path("/some/temp") if platform == "win32" else Path.home()
    assert comm_directory() == plugin.comm_directory() == str(expected / "clo3d_mcp")
    monkeypatch.setenv("CLO3D_MCP_DIR", "/custom")
    assert comm_directory() == "/custom"


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS stdio environment regression")
def test_macos_default_survives_mcp_stdio_environment_filter(plugin, monkeypatch, tmp_path):
    from mcp.client.stdio import get_default_environment
    monkeypatch.delenv("CLO3D_MCP_DIR")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("TMPDIR", "/var/folders/dock/temp")
    monkeypatch.setenv("TEMP", "/another/temp")
    environment = get_default_environment()
    assert "TMPDIR" not in environment and "TEMP" not in environment
    directory = subprocess.check_output([sys.executable, "-c",
        "from clo3d_mcp.ipc import comm_directory; print(comm_directory())"], env=environment, text=True).strip()
    assert directory == plugin.comm_directory() == str(tmp_path / "clo3d_mcp")


def test_wsl_detection_ignores_posix_temp_variables(monkeypatch, tmp_path):
    monkeypatch.delenv("CLO3D_MCP_DIR", raising=False)
    monkeypatch.setattr(ipc.sys, "platform", "linux")
    monkeypatch.setenv("TMPDIR", "/wrong/tmp")
    monkeypatch.setenv("TEMP", "/wrong/temp")
    users = tmp_path / "Users"
    expected = users / "alice/AppData/Local/Temp/clo3d_mcp"
    expected.mkdir(parents=True)
    (users / "Public").mkdir()
    def path(value):
        return users if value == "/mnt/c/Users" else Path(value)
    path.home = Path.home
    monkeypatch.setattr(ipc, "Path", path)
    assert comm_directory() == str(expected)
    monkeypatch.setenv("CLO3D_MCP_DIR", "/explicit/shared")
    assert comm_directory() == "/explicit/shared"


@pytest.mark.parametrize("ready", [False, True])
def test_server_ping_default_has_one_five_second_deadline(monkeypatch, tmp_path, ready):
    import clo3d_mcp.connection as transport
    from clo3d_mcp import server
    if ready:
        BridgeQueue(tmp_path).start()  # Metadata survives, but there is no consumer.
    clock = [0.0]
    monkeypatch.setattr(transport, "time", SimpleNamespace(
        monotonic=lambda: clock[0], sleep=lambda seconds: clock.__setitem__(0, clock[0] + seconds)))
    writes = []
    def publish(path, value):
        writes.append(path)
        atomic_json(path, value)
    monkeypatch.setattr(transport, "atomic_json", publish)
    monkeypatch.setattr(server, "get_connection", lambda: CLO3DConnection(tmp_path))
    with pytest.raises(CLO3DConnectionError):
        server.ping()
    assert 5 <= clock[0] <= 5 + transport.POLL_INTERVAL * 2
    assert len(writes) == int(ready)


@pytest.mark.parametrize("command,api", [("copy_colorway", "CopyColorway"), ("delete_colorway", "DeleteColorwayItem")])
def test_colorway_timeout_never_repeats_sdk_call(bridge, monkeypatch, command, api):
    import clo3d_mcp.connection as transport
    from clo3d_mcp import server
    plugin, connection = bridge
    calls = []
    def mutate(*args):
        calls.append(args)
        time.sleep(.6)
        return 3
    setattr(plugin.utility_api, api, mutate)
    monkeypatch.setattr(transport, "TIMEOUT", .4)
    monkeypatch.setattr(server, "get_connection", lambda: connection)
    with pytest.raises(CLO3DConnectionError, match="not retried"):
        getattr(server, command)(2)
    assert connection.ping()
    assert calls == [(2, 0) if command == "copy_colorway" else (2,)]


def test_session_restart_reports_unknown_outcome(tmp_path):
    first = BridgeQueue(tmp_path)
    first.start()
    connection = CLO3DConnection(tmp_path)
    with concurrent.futures.ThreadPoolExecutor() as pool:
        future = pool.submit(connection.send_command, "mutate", timeout=1)
        deadline = time.monotonic() + 1
        while not list(first.requests.glob("*.json")) and time.monotonic() < deadline:
            time.sleep(.01)
        assert list(first.requests.glob("*.json"))
        BridgeQueue(tmp_path).start()
        with pytest.raises(CLO3DConnectionError, match="outcome is unknown"):
            future.result(2)
    assert not list(first.requests.glob("*.json"))


def test_invalid_command_does_not_stop_bridge(bridge):
    _, connection = bridge
    with pytest.raises(CLO3DConnectionError, match="Invalid command"):
        connection.send_command([], params=[])
    assert connection.ping()
