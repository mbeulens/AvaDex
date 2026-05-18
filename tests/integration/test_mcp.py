import pytest
from avadex.tools.mcp import MCPClient
from avadex.tools.registry import ToolRegistry


@pytest.mark.skipif(
    not __import__("shutil").which("uvx"),
    reason="requires uvx to fetch mcp-server-everything",
)
def test_mcp_lists_tools_from_reference_server():
    client = MCPClient(name="ref", command="uvx", args=["mcp-server-everything"])
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
