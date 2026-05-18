from __future__ import annotations
from pathlib import Path

from avadex.tools.registry import ToolDefinition, ToolResult

MAX_READ_BYTES = 1 * 1024 * 1024  # 1 MB


def read_file_tool(args: dict) -> ToolResult:
    path_str = args.get("path", "")
    if not path_str:
        return ToolResult(content="missing 'path' argument", is_error=True)
    p = Path(path_str)
    if not p.exists():
        return ToolResult(content=f"not found: {p}", is_error=True)
    if not p.is_file():
        return ToolResult(content=f"not a file: {p}", is_error=True)
    if p.stat().st_size > MAX_READ_BYTES:
        return ToolResult(
            content=f"file too large ({p.stat().st_size} bytes, max {MAX_READ_BYTES})",
            is_error=True,
        )
    try:
        return ToolResult(content=p.read_text())
    except UnicodeDecodeError:
        return ToolResult(content=f"file is not utf-8 text: {p}", is_error=True)


READ_FILE = ToolDefinition(
    name="read_file",
    description="Read the full contents of a UTF-8 text file. Returns an error if missing or >1 MB.",
    input_schema={
        "type": "object",
        "properties": {"path": {"type": "string", "description": "Absolute or relative file path."}},
        "required": ["path"],
    },
    handler=read_file_tool,
)


def write_file_tool(args: dict) -> ToolResult:
    path_str = args.get("path", "")
    content = args.get("content")
    if not path_str:
        return ToolResult(content="missing 'path' argument", is_error=True)
    if content is None:
        return ToolResult(content="missing 'content' argument", is_error=True)
    p = Path(path_str)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return ToolResult(content=f"wrote {len(content)} chars to {p}")


WRITE_FILE = ToolDefinition(
    name="write_file",
    description="Create or overwrite a file. Creates parent directories. Returns the byte count written.",
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"},
        },
        "required": ["path", "content"],
    },
    handler=write_file_tool,
)


def edit_file_tool(args: dict) -> ToolResult:
    path_str = args.get("path", "")
    old = args.get("old_string", "")
    new = args.get("new_string", "")
    if not path_str:
        return ToolResult(content="missing 'path' argument", is_error=True)
    p = Path(path_str)
    if not p.exists():
        return ToolResult(content=f"not found: {p}", is_error=True)
    body = p.read_text()
    count = body.count(old)
    if count == 0:
        return ToolResult(content=f"old_string not found in {p}", is_error=True)
    if count > 1:
        return ToolResult(
            content=f"old_string is not unique: appears {count} times in {p}; provide more surrounding context",
            is_error=True,
        )
    p.write_text(body.replace(old, new, 1))
    return ToolResult(content=f"edited {p}")


EDIT_FILE = ToolDefinition(
    name="edit_file",
    description="Replace exactly one occurrence of old_string with new_string in a file. Errors if old_string is missing or appears more than once.",
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "old_string": {"type": "string"},
            "new_string": {"type": "string"},
        },
        "required": ["path", "old_string", "new_string"],
    },
    handler=edit_file_tool,
)
