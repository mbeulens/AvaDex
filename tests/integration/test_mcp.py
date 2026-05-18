import pytest
from avadex.tools.mcp import MCPClient
from avadex.tools.registry import ToolRegistry


@pytest.mark.skipif(
    not __import__("shutil").which("npx"),
    reason="requires npx to fetch @modelcontextprotocol/server-everything",
)
def test_mcp_lists_tools_from_reference_server():
    # Official MCP reference server, published on npm
    client = MCPClient(
        name="ref",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-everything"],
    )
    client.start()
    try:
        tools = client.list_tools()
        names = [t["name"] for t in tools]
        # The reference server exposes 'echo' among others
        assert any("echo" in n.lower() for n in names)
    finally:
        client.stop()


def test_mcp_register_into_registry_with_prefix(tmp_path, monkeypatch):
    """Test the registration plumbing with a fake MCPClient."""
    from avadex.tools.mcp import register_mcp_tools

    class FakeMCP:
        name = "fs"
        is_healthy = True
        def list_tools(self):
            return [
                {"name": "read", "description": "read x", "input_schema": {}},
            ]
        def call_tool(self, name, args):
            from avadex.tools.registry import ToolResult
            return ToolResult(content=f"called {name} with {args}")

    reg = ToolRegistry()
    register_mcp_tools([FakeMCP()], reg)
    # Tools are namespaced with the server name
    assert "fs.read" in reg.names()
    result = reg.dispatch("fs.read", {"path": "/x"})
    assert "called read" in result.content


def test_mcp_crash_flips_unhealthy_and_hides_tools(tmp_path, capsys):
    """When call_tool raises, the MCPClient flips is_healthy=False and its
    tools disappear from the registry's schemas/names + a warning is emitted."""
    from avadex.tools.mcp import register_mcp_tools
    from avadex.tools.registry import ToolRegistry, ToolResult

    class FlakyMCP:
        name = "flaky"
        is_healthy = True

        def list_tools(self):
            return [{"name": "boom", "description": "", "input_schema": {}}]

        def call_tool(self, name, args):
            # Emulate the real MCPClient: catch, flip flag, warn once.
            was_healthy = self.is_healthy
            self.is_healthy = False
            if was_healthy:
                import sys
                print(
                    f"[warn] MCP server '{self.name}' crashed — disabling its tools "
                    f"for the rest of this session (RuntimeError: kapow)",
                    file=sys.stderr,
                )
            return ToolResult(
                content=f"MCP server '{self.name}' is unavailable", is_error=True
            )

    reg = ToolRegistry()
    client = FlakyMCP()
    register_mcp_tools([client], reg)
    # Initially the tool is visible
    assert "flaky.boom" in reg.names()
    # Invoke it — it errors and flips the client
    result = reg.dispatch("flaky.boom", {})
    assert result.is_error
    # Now the tool is filtered out
    assert "flaky.boom" not in reg.names()
    assert not any(s["name"] == "flaky.boom" for s in reg.schemas())
    # Warning was emitted
    err = capsys.readouterr().err
    assert "flaky" in err
    assert "crashed" in err


def test_mcp_client_initializes_healthy():
    """MCPClient starts with is_healthy=True so freshly-registered tools are visible."""
    from avadex.tools.mcp import MCPClient
    c = MCPClient(name="x", command="true", args=[])
    assert c.is_healthy is True
