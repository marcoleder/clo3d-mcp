import concurrent.futures
import json
import multiprocessing
from pathlib import Path
import threading
import time
import uuid

import pytest

from clo3d_mcp.connection import CLO3DConnection, CLO3DConnectionError
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
        time.sleep(.25)
        completed.set()
        return {"done": True}
    plugin.HANDLERS["slow"] = handler
    with pytest.raises(CLO3DConnectionError, match="not retried"):
        connection.send_command("slow", timeout=.15)
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
    with pytest.raises(CLO3DConnectionError, match="No protocol-2"):
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
             "type": "ping", "params": {}, "expires_at": time.time() + 10}
    value.update(overrides)
    atomic_json(queue.requests / (value["id"] + ".json"), value)
    return value


@pytest.mark.parametrize("overrides", [{"expires_at": 0}, {"session": "old"}, {"protocol": 1}])
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
    with pytest.raises(RuntimeError):
        queue.process_one(lambda _: (_ for _ in ()).throw(RuntimeError("crash")))
    second = BridgeQueue(tmp_path)
    second.start()
    assert not second.process_one(lambda _: pytest.fail("replayed"))
    # Even a duplicate pending file cannot override a claimed request.
    atomic_json(second.requests / (value["id"] + ".json"), value)
    assert not second.process_one(lambda _: pytest.fail("replayed"))


def test_duplicate_bridge_lock_rejected(tmp_path):
    with bridge_lock(tmp_path):
        with pytest.raises(RuntimeError, match="already serving"):
            with bridge_lock(tmp_path):
                pytest.fail("two consumers")


def test_defaults_match_plugin(plugin, monkeypatch):
    monkeypatch.delenv("CLO3D_MCP_DIR")
    monkeypatch.delenv("TEMP", raising=False)
    assert comm_directory() == str(Path.home() / "clo3d_mcp")
    monkeypatch.setenv("TEMP", "/some/temp")
    assert comm_directory() == str(Path("/some/temp") / "clo3d_mcp")
    monkeypatch.setenv("CLO3D_MCP_DIR", "/custom")
    assert comm_directory() == "/custom"


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
