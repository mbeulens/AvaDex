import pytest
from avadex.tools.registry import ToolDefinition, ToolRegistry, ToolResult


def test_register_and_dispatch():
    def handler(args):
        return ToolResult(content=f"got {args['x']}")

    reg = ToolRegistry()
    reg.register(ToolDefinition(
        name="echo",
        description="echo x",
        input_schema={"type": "object", "properties": {"x": {"type": "string"}}},
        handler=handler,
    ))

    result = reg.dispatch("echo", {"x": "hi"})
    assert result.content == "got hi"
    assert not result.is_error


def test_schemas_for_request():
    reg = ToolRegistry()
    reg.register(ToolDefinition(
        name="a", description="A tool", input_schema={"type": "object"},
        handler=lambda _: ToolResult(content=""),
    ))
    schemas = reg.schemas()
    assert schemas == [{
        "name": "a",
        "description": "A tool",
        "input_schema": {"type": "object"},
    }]


def test_dispatch_unknown_returns_error():
    reg = ToolRegistry()
    result = reg.dispatch("nope", {})
    assert result.is_error
    assert "unknown tool" in result.content.lower()


def test_dispatch_handler_exception_becomes_tool_error():
    def boom(_):
        raise RuntimeError("kapow")
    reg = ToolRegistry()
    reg.register(ToolDefinition(
        name="boom", description="", input_schema={}, handler=boom,
    ))
    result = reg.dispatch("boom", {})
    assert result.is_error
    assert "kapow" in result.content


def test_unavailable_tool_filtered_from_schemas():
    reg = ToolRegistry()
    healthy = [True]
    reg.register(ToolDefinition(
        name="a", description="", input_schema={"type": "object"},
        handler=lambda _: ToolResult(content=""),
        is_available=lambda: healthy[0],
    ))
    assert len(reg.schemas()) == 1
    healthy[0] = False
    assert len(reg.schemas()) == 0


def test_unavailable_tool_dispatch_returns_error():
    reg = ToolRegistry()
    reg.register(ToolDefinition(
        name="a", description="", input_schema={},
        handler=lambda _: ToolResult(content="ran"),
        is_available=lambda: False,
    ))
    result = reg.dispatch("a", {})
    assert result.is_error
    assert "unavailable" in result.content.lower()


def test_unavailable_tool_filtered_from_names():
    reg = ToolRegistry()
    reg.register(ToolDefinition(
        name="visible", description="", input_schema={}, handler=lambda _: ToolResult(content=""),
    ))
    reg.register(ToolDefinition(
        name="hidden", description="", input_schema={}, handler=lambda _: ToolResult(content=""),
        is_available=lambda: False,
    ))
    names = reg.names()
    assert "visible" in names
    assert "hidden" not in names


def test_tool_server_names_the_mcp_server():
    reg = ToolRegistry()
    reg.register(ToolDefinition(name="read_file", description="", input_schema={},
                                handler=lambda a: ToolResult(content="")))
    reg.register(ToolDefinition(name="syntec-forms_form_list", description="",
                                input_schema={}, handler=lambda a: ToolResult(content=""),
                                server="syntec-forms", inner_name="form_list"))
    assert reg.tool_server("syntec-forms_form_list") == "syntec-forms"
    assert reg.tool_server("read_file") is None
    assert reg.tool_server("nope") is None
