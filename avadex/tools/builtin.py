from __future__ import annotations
from pathlib import Path
import subprocess
import glob as _glob
import re as _re

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


DEFAULT_BASH_TIMEOUT = 30


def bash_tool(args: dict) -> ToolResult:
    cmd = args.get("command", "")
    if not cmd:
        return ToolResult(content="missing 'command' argument", is_error=True)
    timeout = int(args.get("timeout", DEFAULT_BASH_TIMEOUT))
    try:
        proc = subprocess.run(
            cmd,
            shell=True,
            executable="/bin/bash",
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        partial = (exc.stdout or "") + (exc.stderr or "")
        return ToolResult(
            content=f"timed out after {timeout}s\n--- partial output ---\n{partial}",
            is_error=True,
        )
    combined = proc.stdout + proc.stderr
    if proc.returncode != 0:
        return ToolResult(
            content=f"exit code {proc.returncode}\n{combined}",
            is_error=True,
        )
    return ToolResult(content=combined or "(no output)")


BASH = ToolDefinition(
    name="bash",
    description="Run a shell command via /bin/bash. Captures stdout+stderr. Default 30s timeout.",
    input_schema={
        "type": "object",
        "properties": {
            "command": {"type": "string"},
            "timeout": {"type": "integer", "description": "Override timeout in seconds (max 600)."},
        },
        "required": ["command"],
    },
    handler=bash_tool,
)


def glob_tool(args: dict) -> ToolResult:
    pattern = args.get("pattern", "")
    if not pattern:
        return ToolResult(content="missing 'pattern' argument", is_error=True)
    base = args.get("base", ".")
    base_p = Path(base)
    if not base_p.exists():
        return ToolResult(content=f"base not found: {base_p}", is_error=True)
    matches = sorted(_glob.glob(str(base_p / pattern), recursive=True))
    if not matches:
        return ToolResult(content="(no matches)")
    if len(matches) > 200:
        return ToolResult(
            content=f"{len(matches)} matches (showing first 200):\n" + "\n".join(matches[:200])
        )
    return ToolResult(content="\n".join(matches))


GLOB = ToolDefinition(
    name="glob",
    description="Find files matching a glob pattern (** supported for recursion). Returns paths sorted, capped at 200 results.",
    input_schema={
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Glob pattern, e.g. '**/*.py' or 'src/**/test_*.py'"},
            "base": {"type": "string", "description": "Base directory (default: current)"},
        },
        "required": ["pattern"],
    },
    handler=glob_tool,
)


def grep_files_tool(args: dict) -> ToolResult:
    pattern = args.get("pattern", "")
    if not pattern:
        return ToolResult(content="missing 'pattern' argument", is_error=True)
    try:
        rx = _re.compile(pattern)
    except _re.error as exc:
        return ToolResult(content=f"invalid regex: {exc}", is_error=True)
    path_glob = args.get("path_glob", "**/*")
    base = args.get("base", ".")
    max_results = int(args.get("max_results", 100))
    base_p = Path(base)
    if not base_p.exists():
        return ToolResult(content=f"base not found: {base_p}", is_error=True)
    matches = []
    for p in sorted(_glob.glob(str(base_p / path_glob), recursive=True)):
        if not Path(p).is_file():
            continue
        try:
            with open(p, "r", encoding="utf-8", errors="ignore") as f:
                for lineno, line in enumerate(f, 1):
                    if rx.search(line):
                        matches.append(f"{p}:{lineno}:{line.rstrip()}")
                        if len(matches) >= max_results:
                            break
        except OSError:
            continue
        if len(matches) >= max_results:
            break
    if not matches:
        return ToolResult(content="(no matches)")
    truncated = " (capped)" if len(matches) >= max_results else ""
    return ToolResult(content=f"{len(matches)} matches{truncated}:\n" + "\n".join(matches))


GREP_FILES = ToolDefinition(
    name="grep_files",
    description="Search file contents with a Python regex. Returns 'path:lineno:line' entries, capped at max_results (default 100).",
    input_schema={
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Python regex"},
            "path_glob": {"type": "string", "description": "Glob to scope which files to search (default '**/*')"},
            "base": {"type": "string", "description": "Base directory (default: current)"},
            "max_results": {"type": "integer", "description": "Stop after this many matches (default 100)"},
        },
        "required": ["pattern"],
    },
    handler=grep_files_tool,
)


def web_fetch_tool(args: dict) -> ToolResult:
    url = args.get("url", "")
    if not url:
        return ToolResult(content="missing 'url' argument", is_error=True)
    if not url.startswith(("http://", "https://")):
        return ToolResult(content="url must start with http:// or https://", is_error=True)
    max_bytes = int(args.get("max_bytes", 100_000))
    timeout = float(args.get("timeout", 30))
    import httpx
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as c:
            r = c.get(url)
        if r.status_code >= 400:
            return ToolResult(content=f"HTTP {r.status_code} from {url}: {r.text[:200]}", is_error=True)
        body = r.text[:max_bytes]
        truncated = f"\n... (truncated at {max_bytes} bytes; full body {len(r.text)} bytes)" if len(r.text) > max_bytes else ""
        return ToolResult(content=body + truncated)
    except httpx.RequestError as exc:
        return ToolResult(content=f"network error fetching {url}: {exc}", is_error=True)


WEB_FETCH = ToolDefinition(
    name="web_fetch",
    description="HTTP GET a URL and return the response body (up to max_bytes, default 100000). Follows redirects. Returns is_error on 4xx/5xx or network failure.",
    input_schema={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Absolute URL starting with http:// or https://"},
            "max_bytes": {"type": "integer", "description": "Cap response body bytes (default 100000)"},
            "timeout": {"type": "number", "description": "Request timeout in seconds (default 30)"},
        },
        "required": ["url"],
    },
    handler=web_fetch_tool,
)


def multi_edit_tool(args: dict) -> ToolResult:
    path_str = args.get("path", "")
    edits = args.get("edits", [])
    if not path_str:
        return ToolResult(content="missing 'path' argument", is_error=True)
    if not edits or not isinstance(edits, list):
        return ToolResult(content="'edits' must be a non-empty list of {old_string, new_string} objects", is_error=True)
    p = Path(path_str)
    if not p.exists():
        return ToolResult(content=f"not found: {p}", is_error=True)

    body = p.read_text()
    # Validate-and-stage: apply each edit to a working copy. If any edit's
    # old_string is missing or non-unique against the current working state,
    # abort without writing the file.
    for i, e in enumerate(edits, start=1):
        if not isinstance(e, dict) or "old_string" not in e or "new_string" not in e:
            return ToolResult(
                content=f"edit {i}: must be {{old_string, new_string}} object",
                is_error=True,
            )
        old = e["old_string"]
        new = e["new_string"]
        count = body.count(old)
        if count == 0:
            return ToolResult(content=f"edit {i}: old_string not found in {p}", is_error=True)
        if count > 1:
            return ToolResult(
                content=f"edit {i}: old_string appears {count} times in {p} (must be unique); add more surrounding context",
                is_error=True,
            )
        body = body.replace(old, new, 1)

    p.write_text(body)
    return ToolResult(content=f"applied {len(edits)} edits to {p}")


MULTI_EDIT = ToolDefinition(
    name="multi_edit",
    description="Apply multiple {old_string, new_string} edits to one file atomically. Each old_string must appear exactly once in the working state at the moment its edit runs (edits run sequentially). If any edit fails to match, the file is not modified.",
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "edits": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "old_string": {"type": "string"},
                        "new_string": {"type": "string"},
                    },
                    "required": ["old_string", "new_string"],
                },
            },
        },
        "required": ["path", "edits"],
    },
    handler=multi_edit_tool,
)


ALL_BUILTINS = [READ_FILE, WRITE_FILE, EDIT_FILE, BASH, GLOB, GREP_FILES, WEB_FETCH, MULTI_EDIT]
