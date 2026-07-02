from __future__ import annotations
from dataclasses import dataclass
from typing import Callable

from avadex.log import get_logger

log = get_logger("registry")


def _brief_args(args: dict) -> str:
    s = str(args)
    return s if len(s) <= 200 else s[:197] + "..."


@dataclass
class ToolResult:
    # Usually a string; attach_image returns a list of Anthropic content blocks
    # (image + text) that is forwarded verbatim into the tool_result payload.
    content: str | list
    is_error: bool = False


@dataclass
class ToolDefinition:
    name: str
    description: str
    input_schema: dict
    handler: Callable[[dict], ToolResult]
    is_available: Callable[[], bool] = lambda: True


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition):
        self._tools[tool.name] = tool

    def schemas(self) -> list[dict]:
        return [
            {"name": t.name, "description": t.description, "input_schema": t.input_schema}
            for t in self._tools.values()
            if t.is_available()
        ]

    def names(self) -> list[str]:
        return [name for name, t in self._tools.items() if t.is_available()]

    def dispatch(self, name: str, args: dict) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(content=f"unknown tool: {name}", is_error=True)
        if not tool.is_available():
            return ToolResult(content=f"tool '{name}' is currently unavailable", is_error=True)
        log.debug("dispatch tool=%s args=%s", name, _brief_args(args))
        try:
            return tool.handler(args)
        except Exception as exc:
            return ToolResult(content=f"{type(exc).__name__}: {exc}", is_error=True)
