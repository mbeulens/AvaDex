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
