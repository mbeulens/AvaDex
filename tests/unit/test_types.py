import pytest
from avadex.types import (
    TextBlock, ToolUseBlock, AvaResponse,
    parse_response, iter_tool_use_blocks,
)


def test_parse_text_only_response():
    raw = {
        "content": [{"type": "text", "text": "Hello"}],
        "model": "gemma4",
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 10, "output_tokens": 2},
    }
    resp = parse_response(raw)
    assert resp.stop_reason == "end_turn"
    assert len(resp.content) == 1
    assert isinstance(resp.content[0], TextBlock)
    assert resp.content[0].text == "Hello"


def test_parse_tool_use_response():
    raw = {
        "content": [
            {"type": "text", "text": "Let me check."},
            {
                "type": "tool_use",
                "id": "tu_1",
                "name": "read_file",
                "input": {"path": "/etc/hostname"},
            },
        ],
        "model": "gemma4",
        "stop_reason": "tool_use",
        "usage": {"input_tokens": 12, "output_tokens": 8},
    }
    resp = parse_response(raw)
    assert resp.stop_reason == "tool_use"
    tools = list(iter_tool_use_blocks(resp.content))
    assert len(tools) == 1
    assert tools[0].id == "tu_1"
    assert tools[0].name == "read_file"
    assert tools[0].input == {"path": "/etc/hostname"}


def test_parse_unknown_block_type_raises():
    raw = {
        "content": [{"type": "image", "source": "..."}],
        "model": "gemma4",
        "stop_reason": "end_turn",
        "usage": {},
    }
    with pytest.raises(ValueError, match="unknown block type"):
        parse_response(raw)
