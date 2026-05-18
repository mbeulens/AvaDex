from __future__ import annotations
from typing import Protocol
from avadex.tools.registry import ToolResult


class Renderer(Protocol):
    def assistant_text(self, text: str) -> None: ...
    def tool_call(self, name: str, args: dict) -> None: ...
    def tool_result(self, name: str, result: ToolResult) -> None: ...
    def info(self, text: str) -> None: ...
    def error(self, text: str) -> None: ...


class RecordingRenderer:
    """Used in tests; captures every event as a tuple."""
    def __init__(self):
        self.events: list[tuple] = []

    def assistant_text(self, text: str):
        self.events.append(("assistant_text", text))

    def tool_call(self, name: str, args: dict):
        self.events.append(("tool_call", name, args))

    def tool_result(self, name: str, result: ToolResult):
        self.events.append(("tool_result", name, result.content, result.is_error))

    def info(self, text: str):
        self.events.append(("info", text))

    def error(self, text: str):
        self.events.append(("error", text))
