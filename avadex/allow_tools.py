"""Caller-specified tool allowlist (`--allow-tools`).

The caller names exactly which tools a run may use; everything else is hidden
from the model and refused at dispatch. Entries are:

  read_file                     a built-in (or any registered) tool, by name
  mcp__<server>                 every tool of that MCP server
  mcp__<server>__<tool>         one tool of that MCP server, by its MCP name

Fails closed: an entry that matches no registered tool is an error, so a typo
or an MCP server that failed to start stops the run instead of silently
narrowing (or confusing) what the agent can do.
"""
from __future__ import annotations

from avadex.tools.registry import ToolRegistry

MCP_PREFIX = "mcp__"


class AllowToolsError(Exception):
    pass


def parse_allow_tools(spec: str) -> list[str]:
    entries = [e.strip() for e in spec.split(",") if e.strip()]
    if not entries:
        raise AllowToolsError("--allow-tools was given but names no tools")
    return entries


def _matches(entry: str, tool) -> bool:
    if entry == tool.name:
        return True
    if not tool.server:
        return False
    return entry in (f"{MCP_PREFIX}{tool.server}",
                     f"{MCP_PREFIX}{tool.server}__{tool.inner_name}")


def resolve_allowed(entries: list[str], registry: ToolRegistry) -> set[str]:
    """Map allow-tools entries to the registered tool names they grant."""
    tools = registry.all_tools()
    allowed: set[str] = set()
    unmatched: list[str] = []
    for entry in entries:
        hits = {t.name for t in tools if _matches(entry, t)}
        if hits:
            allowed |= hits
        else:
            unmatched.append(entry)
    if unmatched:
        available = sorted(t.name for t in tools)
        raise AllowToolsError(
            f"--allow-tools entries match no available tool: {', '.join(unmatched)} "
            f"(available: {', '.join(available)})"
        )
    return allowed
