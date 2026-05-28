from __future__ import annotations
import sys
from typing import Protocol
from avadex.tools.registry import ToolResult


class Renderer(Protocol):
    def assistant_text(self, text: str) -> None: ...
    def tool_call(self, name: str, args: dict) -> None: ...
    def tool_result(self, name: str, result: ToolResult) -> None: ...
    def info(self, text: str) -> None: ...
    def error(self, text: str) -> None: ...


class HeadlessRenderer:
    """Collects only the final assistant answer; suppresses tool/info noise.

    Used by `avadex --prompt` so that `avadex --prompt "..." > out.txt` produces
    exactly the final answer (no spinners, no tool indicators). Each `tool_call`
    resets the buffer, so intermediate "let me check..." narration emitted
    before a tool call is dropped; only text emitted after the LAST tool call
    (the end_turn answer) survives. Errors go to stderr and set `errored`.
    """

    def __init__(self):
        self._buf: list[str] = []
        self.errored: bool = False

    def assistant_text(self, text: str) -> None:
        self._buf.append(text)

    def tool_call(self, name: str, args: dict) -> None:
        # Discard narration emitted before this tool call; keep only what the
        # model says after the LAST tool call (i.e. the final answer).
        self._buf = []

    def tool_result(self, name: str, result: ToolResult) -> None:
        pass

    def info(self, text: str) -> None:
        pass

    def error(self, text: str) -> None:
        self.errored = True
        print(text, file=sys.stderr)

    @property
    def text(self) -> str:
        return "".join(self._buf)


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
