"""Unchanged Python client against the production native queue/controller.

Build with CLO_BUILD_NATIVE_TESTS=ON; set CLO_NATIVE_HARNESS for other build dirs.
The harness uses fake handlers, never launches CLO or modifies a real scene.
"""
import concurrent.futures
import json
import os
from pathlib import Path
import subprocess
import time
import uuid

import pytest

from clo3d_mcp.connection import CLO3DConnection, CLO3DConnectionError, CLO3DOperationUncertain
from clo3d_mcp.ipc import atomic_json, bridge_lock, read_json

HARNESS = Path(os.environ.get("CLO_NATIVE_HARNESS", str(
    Path(__file__).resolve().parents[1] / "cpp/build-native/clo_queue_harness")))
pytestmark = pytest.mark.skipif(not HARNESS.is_file(), reason="Build the native queue harness first")


def wait_for(predicate, seconds=3):
    until = time.monotonic() + seconds
    while not predicate() and time.monotonic() < until:
        time.sleep(.01)
    assert predicate()


@pytest.fixture
def native(tmp_path):
    process = subprocess.Popen([str(HARNESS), str(tmp_path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    client = CLO3DConnection(tmp_path)
    wait_for(lambda: client.connected or process.poll() is not None)
    assert process.poll() is None, process.communicate()
    yield client, process, tmp_path
    if process.poll() is None:
        (tmp_path / "stop").touch()
        try:
            process.wait(3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def test_client_round_trip_unicode_and_stop(native):
    client, process, directory = native
    ready = read_json(directory / "ready.json")
    assert client.ping()
    assert client.send_command("echo", {"name": "袖 café", "nested": [[], ["x"]]})["echo"]["name"] == "袖 café"
    assert read_json(directory / "ready.json") == ready
    assert client.send_command("stop_bridge") == {"stopped": True}
    assert process.wait(3) == 0
    assert not (directory / "ready.json").exists()


def test_parallel_clients_never_cross_responses(native):
    _, _, directory = native
    def call(i):
        return CLO3DConnection(directory).send_command("echo", {"index": i})["echo"]["index"]
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        assert list(pool.map(call, range(24))) == list(range(24))


def test_native_lock_excludes_python_and_second_native(native):
    _, _, directory = native
    with pytest.raises(RuntimeError, match="already serving"):
        with bridge_lock(directory):
            pytest.fail("Second consumer acquired lock")
    second = subprocess.run([str(HARNESS), str(directory)], capture_output=True, timeout=3)
    assert second.returncode != 0
    assert b"already serving" in second.stderr


def test_python_lock_excludes_native(tmp_path):
    with bridge_lock(tmp_path):
        process = subprocess.run([str(HARNESS), str(tmp_path)], capture_output=True, timeout=3)
    assert process.returncode != 0
    assert b"already serving" in process.stderr
    assert not (tmp_path / "ready.json").exists()


def test_unicode_ipc_directory_and_oversized_message(tmp_path):
    directory = tmp_path / "IPC space 袖"
    process = subprocess.Popen([str(HARNESS), str(directory)])
    try:
        client = CLO3DConnection(directory)
        assert client.ping()
        request_id = uuid.uuid4().hex
        envelope = dict(protocol=3, session=read_json(directory / "ready.json")["session"],
                        id=request_id, type="echo", params={"large": "x" * (16 * 1024 * 1024)}, timeout_seconds=2)
        atomic_json(directory / "requests" / (request_id + ".json"), envelope)
        response = directory / "responses" / (request_id + ".json")
        wait_for(lambda: response.exists())
        assert read_json(response)["status"] == "error"
        assert client.send_command("ping")["calls"] == 0
        assert client.send_command("stop_bridge") == {"stopped": True}
        assert process.wait(3) == 0
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


def request(directory, **overrides):
    value = dict(protocol=3, session=read_json(directory / "ready.json")["session"],
                 id=uuid.uuid4().hex, type="echo", params={}, timeout_seconds=2)
    value.update(overrides)
    atomic_json(directory / "requests" / (value["id"] + ".json"), value)
    return value, directory / "responses" / (value["id"] + ".json")


@pytest.mark.parametrize("changes", [{"protocol": 2}, {"session": "stale"}, {"params": []},
                                       {"type": 2}, {"timeout_seconds": True}, {"timeout_seconds": -1}])
def test_invalid_request_never_dispatches(native, changes):
    client, _, directory = native
    _, response = request(directory, **changes)
    wait_for(lambda: response.exists())
    assert read_json(response)["status"] == "error"
    assert client.send_command("ping")["calls"] == 0


@pytest.mark.parametrize("acknowledge", [False, True])
def test_expired_handshake_never_dispatches(native, acknowledge):
    client, _, directory = native
    value, response = request(directory, timeout_seconds=.2)
    wait_for(lambda: response.exists())
    if acknowledge:
        atomic_json(directory / "requests" / (value["id"] + ".ack"), dict(
            id=value["id"], session=value["session"], token=read_json(response)["token"], timeout_seconds=.0001))
    wait_for(lambda: read_json(response).get("status") == "error")
    assert "expired" in read_json(response)["message"]
    assert client.send_command("ping")["calls"] == 0


def test_queued_timeout_is_not_replayed(native):
    client, _, directory = native
    with concurrent.futures.ThreadPoolExecutor() as pool:
        future = pool.submit(client.send_command, "slow")
        wait_for(lambda: bool(list((directory / "requests").glob("*.working"))))
        time.sleep(.12)
        with pytest.raises(CLO3DConnectionError, match="not retried"):
            CLO3DConnection(directory).send_command("echo", {"bad": True}, timeout=.05)
        assert future.result(3)["calls"] == 1
    assert client.send_command("ping")["calls"] == 1


def test_restart_abandoned_claim_requires_review(tmp_path):
    requests = tmp_path / "requests"
    requests.mkdir()
    (requests / (uuid.uuid4().hex + ".working")).write_text("{}")
    process = subprocess.Popen([str(HARNESS), str(tmp_path)])
    try:
        client = CLO3DConnection(tmp_path)
        assert client.ping()
        assert (tmp_path / "scene-review-required.json").exists()
        assert not list(requests.glob("*.working"))
        with pytest.raises(CLO3DOperationUncertain):
            client.send_command("echo")
        client.send_command("stop_bridge")
        process.wait(3)
        assert (tmp_path / "scene-review-required.json").exists()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


def test_public_tool_input_contract_is_frozen():
    import asyncio
    from clo3d_mcp.server import mcp
    actual = {t.name: t.inputSchema for t in asyncio.run(mcp.list_tools())}
    assert actual == json.loads((Path(__file__).parent / "fixtures/public_tool_schemas.json").read_text())
    catalog = HARNESS.with_name("clo_command_tests" + HARNESS.suffix)
    names = json.loads(subprocess.check_output([str(catalog), "--registry"]))
    aliases = {"save_project": "save_file", "get_pattern_bounding_box": "get_bounding_box",
               "assign_fabric_to_pattern": "assign_fabric"}
    assert set(names) == {aliases.get(name, name) for name in actual}
