from __future__ import annotations
from pathlib import Path

MCP_JSON_FILENAME = ".mcp.json"
DOTENV_FILENAME = ".env"


def load_dotenv(path: Path) -> dict[str, str]:
    """Parse a simple KEY=VALUE .env file into a dict. Missing file -> {}.

    Skips blank lines and '#' comments, tolerates a leading 'export ',
    splits on the first '=', and strips one layer of matching surrounding
    quotes. Does NOT mutate os.environ.
    """
    if not path.exists():
        return {}
    result: dict[str, str] = {}
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
            val = val[1:-1]
        if key:
            result[key] = val
    return result


def claude_to_raw(mcp_json: dict) -> list[dict]:
    """Translate Claude's `.mcp.json` (a `mcpServers` map) into the raw-dict
    shape that `config._parse_mcp_servers` consumes: the dict key becomes
    `name`, Claude's `type` becomes `transport` (default `stdio`), and
    command/args/url/headers are carried through.
    """
    servers = mcp_json.get("mcpServers", {})
    raw: list[dict] = []
    for name, entry in servers.items():
        raw.append({
            "name": name,
            "transport": entry.get("type", "stdio"),
            "command": entry.get("command", ""),
            "args": entry.get("args", []),
            "url": entry.get("url", ""),
            "headers": entry.get("headers", {}),
        })
    return raw
