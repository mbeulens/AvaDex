"""Module-local todo list for a single AvaDex session.

State lives at module scope — fine for a single-user, single-process CLI.
The model writes the full list on each todo_write call (no delta updates),
mirroring how Claude Code's TodoWrite tool behaves.
"""
from __future__ import annotations

from avadex.tools.registry import ToolDefinition, ToolResult


_TODOS: list[dict] = []
_VALID_STATUSES = {"pending", "in_progress", "completed"}


def _render(todos: list[dict]) -> str:
    if not todos:
        return "(no todos)"
    symbols = {"pending": "[ ]", "in_progress": "[~]", "completed": "[x]"}
    return "\n".join(
        f"  {symbols.get(t['status'], '[?]')} {t['content']}"
        for t in todos
    )


def todo_write_tool(args: dict) -> ToolResult:
    todos = args.get("todos")
    if todos is None or not isinstance(todos, list):
        return ToolResult(content="'todos' must be a list", is_error=True)
    cleaned: list[dict] = []
    for i, t in enumerate(todos, start=1):
        if not isinstance(t, dict):
            return ToolResult(content=f"todo {i}: must be an object", is_error=True)
        content = t.get("content")
        status = t.get("status", "pending")
        if not content or not isinstance(content, str):
            return ToolResult(content=f"todo {i}: 'content' must be a non-empty string", is_error=True)
        if status not in _VALID_STATUSES:
            return ToolResult(
                content=f"todo {i}: status must be one of {sorted(_VALID_STATUSES)}",
                is_error=True,
            )
        cleaned.append({"content": content, "status": status})
    _TODOS.clear()
    _TODOS.extend(cleaned)
    return ToolResult(content=f"{len(cleaned)} todos:\n{_render(_TODOS)}")


def todo_read_tool(args: dict) -> ToolResult:
    return ToolResult(content=_render(_TODOS))


def _reset_for_tests() -> None:
    """Test helper to clear module state between tests."""
    _TODOS.clear()


TODO_WRITE = ToolDefinition(
    name="todo_write",
    description="Replace the session's todo list. Pass {todos: [{content: str, status: 'pending'|'in_progress'|'completed'}]}. Use this to plan multi-step work and update progress so the user can follow along.",
    input_schema={
        "type": "object",
        "properties": {
            "todos": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string"},
                        "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]},
                    },
                    "required": ["content"],
                },
            }
        },
        "required": ["todos"],
    },
    handler=todo_write_tool,
)


TODO_READ = ToolDefinition(
    name="todo_read",
    description="Return the current session todo list.",
    input_schema={"type": "object", "properties": {}},
    handler=todo_read_tool,
)
