"""The same result normalization examples are consumed by native command tests."""
import asyncio
import json
from pathlib import Path

import pytest

from clo3d_mcp.contracts import FAILURE_FLAGS, export_paths

CONTRACTS = json.loads((Path(__file__).parent / "fixtures/result_contracts.json").read_text())


@pytest.mark.parametrize("case", CONTRACTS["export_paths"])
def test_shared_export_paths(case):
    if case.get("error"):
        with pytest.raises(ValueError):
            export_paths(case["input"])
    else:
        assert export_paths(case["input"]) == case["output"]


def test_shared_failure_flags():
    assert FAILURE_FLAGS == set(CONTRACTS["failure_flags"])


def test_public_tool_input_contract_is_frozen():
    from clo3d_mcp.server import mcp
    actual = {t.name: t.inputSchema for t in asyncio.run(mcp.list_tools())}
    assert actual == json.loads((Path(__file__).parent / "fixtures/public_tool_schemas.json").read_text())


def test_every_clo_tool_dispatches_to_a_python_handler(plugin, monkeypatch):
    from clo3d_mcp import server
    commands = []
    def send(command, params=None):
        assert callable(plugin.HANDLERS[command])
        commands.append(command)
        return {}
    monkeypatch.setattr(server, "_send", send)
    async def check():
        tools = await server.mcp.list_tools()
        assert len(tools) == 49
        examples = {"string": "fixture", "integer": 0, "number": 0, "boolean": False, "array": [], "object": {}}
        for tool in tools:
            if tool.name == "export_diagnostics":
                continue  # Local support tool, tested without a live bridge.
            schema = tool.inputSchema
            params = {key: examples[schema["properties"][key]["type"]] for key in schema.get("required", [])}
            before = len(commands)
            await server.mcp.call_tool(tool.name, params)
            assert len(commands) == before + 1
    asyncio.run(check())
    assert set(commands) == {name for name in plugin.HANDLERS if not name.startswith("debug_")}
