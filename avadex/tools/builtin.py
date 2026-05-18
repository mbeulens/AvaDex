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
