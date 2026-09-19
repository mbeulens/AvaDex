from __future__ import annotations
from dataclasses import dataclass, field
from typing import Iterator, Union


@dataclass
class TextBlock:
    text: str
    type: str = "text"


@dataclass
class ToolUseBlock:
    id: str
    name: str
    input: dict
    type: str = "tool_use"


@dataclass
class ToolResultBlock:
    tool_use_id: str
    content: str | list
    is_error: bool = False
    type: str = "tool_result"


Block = Union[TextBlock, ToolUseBlock, ToolResultBlock]


@dataclass
class AvaResponse:
    content: list[Block]
    model: str
    stop_reason: str
    usage: dict = field(default_factory=dict)
    ava: dict | None = None   # Ava's key-policy block (Ava >= 0.4.6), see avadex.key_policy


def parse_block(raw: dict) -> Block:
    t = raw.get("type")
    if t == "text":
        return TextBlock(text=raw.get("text", ""))
    if t == "tool_use":
        return ToolUseBlock(
            id=raw["id"], name=raw["name"], input=raw.get("input", {})
        )
    if t == "tool_result":
        return ToolResultBlock(
            tool_use_id=raw["tool_use_id"],
            content=raw.get("content", ""),
            is_error=raw.get("is_error", False),
        )
    raise ValueError(f"unknown block type: {t!r}")


def parse_response(raw: dict) -> AvaResponse:
    return AvaResponse(
        content=[parse_block(b) for b in raw.get("content", [])],
        model=raw.get("model", ""),
        stop_reason=raw.get("stop_reason", "end_turn"),
        usage=raw.get("usage", {}),
        ava=raw.get("ava") if isinstance(raw.get("ava"), dict) else None,
    )


def block_to_dict(block: Block) -> dict:
    if isinstance(block, TextBlock):
        return {"type": "text", "text": block.text}
    if isinstance(block, ToolUseBlock):
        return {
            "type": "tool_use",
            "id": block.id,
            "name": block.name,
            "input": block.input,
        }
    if isinstance(block, ToolResultBlock):
        d = {
            "type": "tool_result",
            "tool_use_id": block.tool_use_id,
            "content": block.content,
        }
        if block.is_error:
            d["is_error"] = True
        return d
    raise TypeError(f"unknown block: {block!r}")


def iter_tool_use_blocks(content: list[Block]) -> Iterator[ToolUseBlock]:
    for b in content:
        if isinstance(b, ToolUseBlock):
            yield b
