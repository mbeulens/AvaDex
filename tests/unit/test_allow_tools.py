import pytest

from avadex.allow_tools import AllowToolsError, parse_allow_tools, resolve_allowed
from avadex.tools.registry import ToolDefinition, ToolRegistry, ToolResult


def _tool(name, server="", inner_name=""):
    return ToolDefinition(
        name=name, description=name, input_schema={"type": "object"},
        handler=lambda args, _n=name: ToolResult(content=f"ran {_n}"),
        server=server, inner_name=inner_name,
    )


@pytest.fixture
def registry():
    reg = ToolRegistry()
    for name in ("read_file", "write_file", "bash", "grep_files", "load_skill"):
        reg.register(_tool(name))
    reg.register(_tool("syntec_forms_get_form", server="syntec-forms", inner_name="get_form"))
    reg.register(_tool("syntec_forms_list_forms", server="syntec-forms", inner_name="list_forms"))
    reg.register(_tool("partners_search", server="partners", inner_name="search"))
    return reg


# --- parse_allow_tools ---------------------------------------------------

def test_parse_splits_on_commas_and_strips():
    assert parse_allow_tools(" read_file, grep_files ,mcp__x ") == [
        "read_file", "grep_files", "mcp__x"]


def test_parse_rejects_empty_spec():
    # An empty set is almost certainly a caller bug; refuse rather than run
    # an agent with zero tools that the caller didn't ask for.
    with pytest.raises(AllowToolsError):
        parse_allow_tools(" , ")


# --- resolve_allowed ------------------------------------------------------

def test_builtin_names_match_exactly(registry):
    assert resolve_allowed(["read_file", "grep_files"], registry) == {
        "read_file", "grep_files"}


def test_mcp_server_prefix_grants_every_tool_of_that_server(registry):
    assert resolve_allowed(["mcp__syntec-forms"], registry) == {
        "syntec_forms_get_form", "syntec_forms_list_forms"}


def test_mcp_server_and_tool_grants_one_tool(registry):
    assert resolve_allowed(["mcp__syntec-forms__get_form"], registry) == {
        "syntec_forms_get_form"}


def test_registered_mcp_name_also_accepted(registry):
    assert resolve_allowed(["partners_search"], registry) == {"partners_search"}


def test_entry_matching_nothing_fails_closed(registry):
    # A typo, a tool that doesn't exist, or an MCP server that failed to start
    # all mean the caller's intent can't be honoured — refuse to run.
    with pytest.raises(AllowToolsError) as exc:
        resolve_allowed(["read_file", "mcp__syntec-form", "bassh"], registry)
    assert "mcp__syntec-form" in str(exc.value)
    assert "bassh" in str(exc.value)


# --- ToolRegistry.restrict ------------------------------------------------

def test_restrict_hides_other_tools_from_schemas(registry):
    registry.restrict({"read_file", "syntec_forms_get_form"})
    names = [s["name"] for s in registry.schemas()]
    assert sorted(names) == ["read_file", "syntec_forms_get_form"]
    assert sorted(registry.names()) == ["read_file", "syntec_forms_get_form"]


def test_restrict_rejects_dispatch_of_hidden_tool(registry):
    # A hallucinated or remembered tool name must not get through dispatch.
    registry.restrict({"read_file"})
    result = registry.dispatch("bash", {"command": "rm -rf /tmp/probe"})
    assert result.is_error
    assert "not permitted" in result.content


def test_restrict_still_dispatches_allowed_tool(registry):
    registry.restrict({"read_file"})
    result = registry.dispatch("read_file", {})
    assert not result.is_error
    assert result.content == "ran read_file"


def test_unrestricted_registry_exposes_everything(registry):
    assert len(registry.schemas()) == 8


def test_register_mcp_tools_records_server_and_inner_name():
    from avadex.tools.mcp import register_mcp_tools

    class FakeClient:
        name = "syntec-forms"
        is_healthy = True

        def list_tools(self):
            return [{"name": "get.form", "description": "d", "input_schema": {}}]

    reg = ToolRegistry()
    register_mcp_tools([FakeClient()], reg)
    assert resolve_allowed(["mcp__syntec-forms__get.form"], reg) == {"syntec_forms_get_form"}
    assert resolve_allowed(["mcp__syntec-forms"], reg) == {"syntec_forms_get_form"}
