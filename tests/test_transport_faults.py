"""Disk faults and independent clocks must never replay an uncertain mutation."""
import concurrent.futures
import errno
import json
from pathlib import Path
import threading
import time
from types import SimpleNamespace
import uuid

import pytest

from clo3d_mcp import connection as client_module, ipc
from clo3d_mcp.connection import CLO3DConnection, CLO3DConnectionError, CLO3DOperationUncertain
from clo3d_mcp.contracts import OperationOutcomeUnknown


def queued(queue, **overrides):
    value = dict(id=uuid.uuid4().hex, protocol=ipc.PROTOCOL, session=queue.session,
                 type="mutate", params={}, timeout_seconds=10)
    value.update(overrides)
    ipc.atomic_json(queue.requests / (value["id"] + ".json"), value)
    return value


def acknowledge(queue, value, remaining=10):
    offer = ipc.read_json(queue.responses / (value["id"] + ".json"))
    assert offer["status"] == "claimed"
    ipc.atomic_json(queue.requests / (value["id"] + ".ack"), dict(
        id=value["id"], session=queue.session, token=offer["token"], timeout_seconds=remaining))


def wait_for(predicate):
    deadline = time.monotonic() + 3
    while not predicate() and time.monotonic() < deadline:
        time.sleep(.01)
    assert predicate()


@pytest.mark.parametrize("code", [errno.ENOSPC, errno.EACCES, errno.EBUSY])
def test_failed_review_write_keeps_bridge_alive_and_mutations_blocked(bridge, monkeypatch, code):
    plugin, connection = bridge
    calls = []
    def mutate(params):
        calls.append(params)
        raise OperationOutcomeUnknown("failed after adding avatar")
    plugin.HANDLERS["mutate"] = mutate
    def fail(*args):
        raise OSError(code, "injected marker write failure")
    monkeypatch.setattr(plugin, "atomic_json", fail)
    with pytest.raises(CLO3DOperationUncertain):
        connection.send_command("mutate")
    assert not Path(plugin._review_file()).exists()
    assert plugin._review_required()
    assert list((Path(plugin.COMM_DIR) / "requests").glob("*.working"))
    assert connection.ping()
    with pytest.raises(CLO3DOperationUncertain):
        connection.send_command("mutate")
    assert len(calls) == 1


@pytest.mark.parametrize("review_also_fails", [False, True])
def test_response_write_failure_does_not_stop_or_replay_command(bridge, monkeypatch, review_also_fails):
    plugin, connection = bridge
    calls = []
    plugin.HANDLERS["mutate"] = lambda params: calls.append(params) or {"mutated": True}
    real_write = ipc.atomic_json
    def fail_result(path, value):
        if value.get("result", {}).get("mutated"):
            raise OSError(errno.ENOSPC, "injected response write failure")
        real_write(path, value)
    monkeypatch.setattr(ipc, "atomic_json", fail_result)
    if review_also_fails:
        def fail_marker(*args):
            raise OSError(errno.ENOSPC, "injected review write failure")
        monkeypatch.setattr(plugin, "atomic_json", fail_marker)
    with pytest.raises(CLO3DConnectionError, match="not retried"):
        connection.send_command("mutate", timeout=.5)
    assert connection.ping()
    assert len(calls) == 1
    assert plugin._review_required()
    assert Path(plugin._review_file()).is_file() is not review_also_fails


def test_restart_preserves_abandoned_claim_until_review_can_be_persisted(plugin, monkeypatch):
    queue = ipc.BridgeQueue(plugin.COMM_DIR)
    queue.start()
    value = queued(queue)
    queue.process_one(lambda _: pytest.fail("not acknowledged"))
    acknowledge(queue, value)
    with pytest.raises(RuntimeError):
        queue.process_one(lambda _: (_ for _ in ()).throw(RuntimeError("process died after native call")))
    real_write = plugin.atomic_json
    def fail(*args):
        raise OSError(errno.ENOSPC, "review disk full")
    monkeypatch.setattr(plugin, "atomic_json", fail)
    second = ipc.BridgeQueue(plugin.COMM_DIR)
    second.start(on_abandoned=plugin._abandoned_claims)
    claim = second.requests / (value["id"] + ".working")
    assert claim.exists() and plugin._review_required()
    response = json.loads(plugin.process_command(json.dumps(dict(type="new_project", params={}))))
    assert response["outcome"] == "unknown"
    monkeypatch.setattr(plugin, "atomic_json", real_write)
    assert plugin._persist_review()
    second.retire_abandoned()
    assert not claim.exists()
    plugin._review_state = None  # New interpreter still sees the durable block.
    assert plugin._review_required()


def test_startup_removes_old_responses_claims_and_acknowledgements(tmp_path):
    first = ipc.BridgeQueue(tmp_path)
    first.start()
    value = queued(first)
    first.process_one(lambda _: pytest.fail("not acknowledged"))
    acknowledge(first, value)
    orphan_response = first.responses / (uuid.uuid4().hex + ".json")
    ipc.atomic_json(orphan_response, {"status": "success"})
    seen = []
    second = ipc.BridgeQueue(tmp_path)
    second.start(on_abandoned=lambda claims: seen.extend(claims) or True)
    assert len(seen) == 1
    assert not list(second.responses.iterdir())
    assert not list(second.requests.iterdir())
    fresh = queued(second)
    second.process_one(lambda _: pytest.fail("not acknowledged"))
    acknowledge(second, fresh)
    calls = []
    second.process_one(lambda text: calls.append(text) or json.dumps({"id": fresh["id"], "status": "success"}))
    assert len(calls) == 1


@pytest.mark.parametrize("offset", [-86400, 86400])
def test_independent_wall_and_monotonic_clock_origins_do_not_expire_fresh_calls(bridge, monkeypatch, offset):
    _, connection = bridge
    def forbidden_wall_clock():
        pytest.fail("IPC must not use wall-clock timestamps")
    monkeypatch.setattr(client_module, "time", SimpleNamespace(
        time=forbidden_wall_clock, monotonic=lambda: time.monotonic() + offset, sleep=time.sleep))
    monkeypatch.setattr(ipc, "time", SimpleNamespace(
        time=forbidden_wall_clock, monotonic=lambda: time.monotonic() - offset))
    assert connection.ping()


@pytest.mark.parametrize("acknowledged", [False, True])
def test_expired_or_abandoned_claim_never_dispatches(tmp_path, monkeypatch, acknowledged):
    now = [100.0]
    monkeypatch.setattr(ipc, "time", SimpleNamespace(monotonic=lambda: now[0]))
    queue = ipc.BridgeQueue(tmp_path)
    queue.start()
    value = queued(queue)
    queue.process_one(lambda _: pytest.fail("not acknowledged"))
    if acknowledged:
        acknowledge(queue, value, remaining=.1)
        now[0] += .2
    else:
        now[0] += ipc.ACK_TIMEOUT + 1
    queue.process_one(lambda _: pytest.fail("abandoned/expired mutation executed"))
    assert "expired" in ipc.read_json(queue.responses / (value["id"] + ".json"))["message"]


def test_queued_timeout_during_long_native_call_does_not_execute_later(bridge):
    plugin, connection = bridge
    started, finish = threading.Event(), threading.Event()
    def slow(params):
        started.set()
        assert finish.wait(3)
        return {}
    plugin.HANDLERS["slow"] = slow
    plugin.HANDLERS["mutate"] = lambda _: pytest.fail("timed-out queued mutation executed")
    with concurrent.futures.ThreadPoolExecutor() as pool:
        future = pool.submit(connection.send_command, "slow")
        assert started.wait(2)
        try:
            with pytest.raises(CLO3DConnectionError, match="not retried"):
                CLO3DConnection(plugin.COMM_DIR).send_command("mutate", timeout=.1)
        finally:
            finish.set()
        assert future.result(2) == {}
    assert connection.ping()


def test_client_with_claim_response_exits_promptly_when_session_changes(tmp_path):
    queue = ipc.BridgeQueue(tmp_path)
    queue.start()
    with concurrent.futures.ThreadPoolExecutor() as pool:
        future = pool.submit(CLO3DConnection(tmp_path).send_command, "mutate", timeout=2)
        wait_for(lambda: bool(list(queue.requests.glob("*.json"))))
        queue.process_one(lambda _: pytest.fail("not acknowledged"))
        ipc.atomic_json(queue.ready, {"protocol": ipc.PROTOCOL, "session": "replacement"})
        with pytest.raises(CLO3DConnectionError, match="outcome is unknown"):
            future.result(1)
