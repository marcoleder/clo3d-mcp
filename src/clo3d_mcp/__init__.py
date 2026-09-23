"""CLO3D MCP Server — Control CLO3D via the Model Context Protocol."""

__version__ = "0.1.0"


def main():
    """Entry point for the MCP server (used by uvx/pip scripts)."""
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "diagnostics":
        from clo3d_mcp.diagnostics import main as diagnostics_main
        raise SystemExit(diagnostics_main(sys.argv[2:]))
    from clo3d_mcp.server import mcp
    mcp.run()
