"""Exercise the actual stdio MCP server against a fake in-process CLO bridge."""
import asyncio
import os
import sys
from datetime import timedelta

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def test_stdio_discovery_success_and_handler_error(bridge):
    plugin, connection = bridge
    calls = []
    def failed_simulation(steps):
        calls.append(steps)
        return False
    plugin.utility_api.Simulate = failed_simulation

    async def check():
        params = StdioServerParameters(
            command=sys.executable,
            args=["-c", "from clo3d_mcp import main; main()"],
            env={**os.environ, "CLO3D_MCP_DIR": connection.comm_dir},
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=10)) as session:
                await session.initialize()
                listing = await session.list_tools()
                names = {tool.name for tool in listing.tools}
                assert "stop_bridge" in names
                assert len(names) == 48
                assert not (await session.call_tool("ping", {})).isError
                result = await session.call_tool("simulate", {"steps": 1})
                assert result.isError
                assert "Simulate returned false" in str(result.content)
                assert not (await session.call_tool("stop_bridge", {})).isError
    asyncio.run(check())
    assert calls == [1]
