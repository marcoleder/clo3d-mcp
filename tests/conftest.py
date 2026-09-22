"""Run the production bridge loop with fake CLO APIs; no duplicate IPC server."""
import importlib.util
from pathlib import Path
import sys
import threading
import time
import types

import pytest

from clo3d_mcp.connection import CLO3DConnection


@pytest.fixture
def plugin(tmp_path, monkeypatch):
    monkeypatch.setenv("CLO3D_MCP_DIR", str(tmp_path))
    for name in ("export_api", "fabric_api", "import_api", "pattern_api", "utility_api"):
        monkeypatch.setitem(sys.modules, name, types.SimpleNamespace())
    path = Path(__file__).resolve().parents[1] / "plugin/clo3d_mcp_plugin.py"
    spec = importlib.util.spec_from_file_location("clo3d_mcp_plugin", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "_shim", lambda: None)
    return module


@pytest.fixture
def bridge(plugin):
    plugin._server_running = True
    thread = threading.Thread(target=plugin.poll_loop, daemon=True)
    thread.start()
    connection = CLO3DConnection(plugin.COMM_DIR)
    deadline = time.monotonic() + 2
    while not connection.connected and time.monotonic() < deadline:
        time.sleep(.01)
    assert connection.connected
    yield plugin, connection
    plugin._server_running = False
    thread.join(3)
    assert not thread.is_alive()
