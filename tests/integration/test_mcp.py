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
    assert "fs_read" in reg.names()
    result = reg.dispatch("fs_read", {"path": "/x"})
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
    assert "flaky_boom" in reg.names()
    # Invoke it — it errors and flips the client
    result = reg.dispatch("flaky_boom", {})
    assert result.is_error
    # Now the tool is filtered out
    assert "flaky_boom" not in reg.names()
    assert not any(s["name"] == "flaky_boom" for s in reg.schemas())
    # Warning was emitted
    err = capsys.readouterr().err
    assert "flaky" in err
    assert "crashed" in err


def test_mcp_register_sanitizes_tool_names():
    """Namespaced names are sanitized to valid function-name chars (no dots or
    hyphens) so models can reproduce them; the real MCP call still uses the
    original tool name."""
    from avadex.tools.mcp import register_mcp_tools
    from avadex.tools.registry import ToolResult

    class FakeMCP:
        name = "syntec-enterprise-landen"
        is_healthy = True
        def list_tools(self):
            return [{"name": "s_cty_list", "description": "", "input_schema": {}}]
        def call_tool(self, name, args):
            return ToolResult(content=f"called {name}")

    reg = ToolRegistry()
    register_mcp_tools([FakeMCP()], reg)
    assert "syntec_enterprise_landen_s_cty_list" in reg.names()
    # no dots or hyphens survive in any registered name
    assert all("." not in n and "-" not in n for n in reg.names())
    # dispatch by the sanitized name still invokes the ORIGINAL tool name
    result = reg.dispatch("syntec_enterprise_landen_s_cty_list", {})
    assert "called s_cty_list" in result.content


def test_mcp_client_initializes_healthy():
    """MCPClient starts with is_healthy=True so freshly-registered tools are visible."""
    from avadex.tools.mcp import MCPClient
    c = MCPClient(name="x", command="true", args=[])
    assert c.is_healthy is True


def test_mcp_client_stores_transport_fields():
    from avadex.tools.mcp import MCPClient
    c = MCPClient(
        name="remote", transport="http",
        url="https://mcp.example.com/mcp",
        headers={"Authorization": "Bearer x"},
    )
    assert c.transport == "http"
    assert c.url == "https://mcp.example.com/mcp"
    assert c.headers == {"Authorization": "Bearer x"}


def test_open_transport_selects_client_per_transport(monkeypatch):
    import mcp.client.stdio, mcp.client.sse, mcp.client.streamable_http
    from avadex.tools.mcp import MCPClient, _open_transport

    # _open_transport does `from mcp.client.X import Y` at call time, so patching
    # the source-module attribute is seen by the fresh import. Each stub returns
    # a sentinel instead of a real (network-opening) context manager.
    monkeypatch.setattr(mcp.client.stdio, "stdio_client", lambda params: "STDIO")
    monkeypatch.setattr(mcp.client.sse, "sse_client", lambda url, headers=None: "SSE")
    monkeypatch.setattr(mcp.client.streamable_http, "streamablehttp_client",
                        lambda url, headers=None: "HTTP")

    assert _open_transport(MCPClient(name="a", command="true")) == "STDIO"
    assert _open_transport(
        MCPClient(name="b", transport="http", url="https://h/mcp", headers={"X": "1"})
    ) == "HTTP"
    assert _open_transport(
        MCPClient(name="c", transport="sse", url="https://s/sse")
    ) == "SSE"


def test_open_transport_unknown_raises():
    from avadex.tools.mcp import MCPClient, _open_transport
    bad = MCPClient(name="x", transport="bogus", url="https://x")
    with pytest.raises(ValueError, match="bogus"):
        _open_transport(bad)


def test_open_transport_imports_the_real_sdk_clients():
    # No monkeypatching: this is the guard for an SDK that renames a client
    # (mcp 2.x dropped `streamablehttp_client`). The factories only build a
    # context manager; nothing connects until it is entered.
    from avadex.tools.mcp import MCPClient, _open_transport
    for transport, url in (("http", "https://h/mcp"), ("sse", "https://s/sse")):
        cm = _open_transport(MCPClient(name=transport, transport=transport, url=url,
                                       headers={"Authorization": "Bearer x"}))
        assert hasattr(cm, "__aenter__")
