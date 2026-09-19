from __future__ import annotations
import base64
import copy
import sys
from typing import Protocol
from avadex.tools.registry import ToolResult


class Renderer(Protocol):
    def assistant_text(self, text: str) -> None: ...
    def tool_call(self, name: str, args: dict) -> None: ...
    def tool_result(self, name: str, result: ToolResult) -> None: ...
    def info(self, text: str) -> None: ...
    def error(self, text: str) -> None: ...
    # Optional: tool_skipped(name, args, reason) for calls the model requested
    # that the loop aborted before running. Callers use getattr.


class HeadlessRenderer:
    """Collects only the final assistant answer; suppresses tool/info noise.

    Used by `avadex --prompt` so that `avadex --prompt "..." > out.txt` produces
    exactly the final answer (no spinners, no tool indicators). Each `tool_call`
    resets the buffer, so intermediate "let me check..." narration emitted
    before a tool call is dropped; only text emitted after the LAST tool call
    (the end_turn answer) survives. Errors go to stderr and set `errored`.

    It also keeps `transcript`: every tool call with its input and its result,
    verbatim, for `--output-format json`. Callers read facts from it instead
    of from the model's summary, so nothing is truncated, failed calls are
    flagged rather than dropped, and a call with no result stays in with a
    null output.
    """

    def __init__(self):
        self._buf: list[str] = []
        self.errors: list[str] = []
        self._calls: list[dict] = []

    def assistant_text(self, text: str) -> None:
        self._buf.append(text)

    def tool_call(self, name: str, args: dict) -> None:
        # Discard narration emitted before this tool call; keep only what the
        # model says after the LAST tool call (i.e. the final answer).
        self._buf = []
        self._calls.append({"tool": name, "input": copy.deepcopy(args),
                            "output": None, "is_error": None, "status": "no_result"})

    def tool_result(self, name: str, result: ToolResult) -> None:
        # Calls run one at a time, so the result belongs to the latest open
        # call of that name.
        for call in reversed(self._calls):
            if call["tool"] == name and call["status"] == "no_result":
                call["output"] = _transcript_output(result.content)
                call["is_error"] = bool(result.is_error)
                call["status"] = "error" if result.is_error else "ok"
                return

    def tool_skipped(self, name: str, args: dict, reason: str) -> None:
        self._calls.append({"tool": name, "input": copy.deepcopy(args),
                            "output": None, "is_error": None, "status": "not_run",
                            "reason": reason})

    def info(self, text: str) -> None:
        pass

    def error(self, text: str) -> None:
        self.errors.append(text)
        print(text, file=sys.stderr)

    @property
    def errored(self) -> bool:
        return bool(self.errors)

    @property
    def text(self) -> str:
        return "".join(self._buf)

    @property
    def transcript(self) -> list[dict]:
        return copy.deepcopy(self._calls)


def _transcript_output(content):
    """A tool result as it goes into the transcript: strings verbatim; for
    block lists (attach_image), image data is replaced by its type and size."""
    if not isinstance(content, list):
        return content
    out = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "image":
            src = block.get("source") or {}
            try:
                size = len(base64.b64decode(src.get("data") or ""))
            except (ValueError, TypeError):
                size = None
            out.append({"type": "image", "media_type": src.get("media_type"), "bytes": size})
        else:
            out.append(block)
    return out


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

    def tool_skipped(self, name: str, args: dict, reason: str):
        self.events.append(("tool_skipped", name, args, reason))

    def info(self, text: str):
        self.events.append(("info", text))

    def error(self, text: str):
        self.events.append(("error", text))
