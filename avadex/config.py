from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
import os
import re

try:
    import tomllib as _tomli
except ImportError:
    import tomli as _tomli

import tomli_w


class ConfigMissing(Exception):
    pass


@dataclass
class MCPServerConfig:
    name: str
    transport: str = "stdio"
    command: str = ""
    args: list[str] = field(default_factory=list)
    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class Config:
    ava_url: str
    ava_token: str
    default_model: str = ""  # empty = resolve from Ava's /api/v1/models on startup
    max_context_tokens: int = 3500
    system_prompt_path: str = ""
    mcp_servers: list[MCPServerConfig] = field(default_factory=list)


def load_config(path: Path) -> Config:
    p = Path(path)
    if not p.exists():
        raise ConfigMissing(f"no config at {p}; run 'avadex login'")
    with open(p, "rb") as f:
        data = _tomli.load(f)
    try:
        return Config(
            ava_url=data["ava_url"],
            ava_token=data["ava_token"],
            default_model=data.get("default_model", ""),
            max_context_tokens=data.get("max_context_tokens", 3500),
            system_prompt_path=data.get("system_prompt_path", ""),
            mcp_servers=_parse_mcp_servers(data.get("mcp_servers", [])),
        )
    except KeyError as exc:
        raise ConfigMissing(
            f"config at {p} is missing required field {exc.args[0]!r}; run 'avadex login'"
        ) from exc


_ENV_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _interpolate_env(value: str, *, server: str, header: str) -> str:
    def repl(match: re.Match) -> str:
        var = match.group(1)
        try:
            return os.environ[var]
        except KeyError:
            raise ConfigMissing(
                f"MCP server {server!r} header {header!r} references "
                f"${{{var}}} but environment variable {var!r} is not set"
            ) from None
    return _ENV_RE.sub(repl, value)


_VALID_TRANSPORTS = {"stdio", "http", "sse"}


def _parse_mcp_servers(raw: list[dict]) -> list[MCPServerConfig]:
    servers: list[MCPServerConfig] = []
    for entry in raw:
        name = entry.get("name")
        if not name:
            raise ConfigMissing("an mcp_servers entry is missing required field 'name'")
        transport = entry.get("transport", "stdio")
        if transport not in _VALID_TRANSPORTS:
            raise ConfigMissing(
                f"MCP server {name!r} has invalid transport {transport!r}; "
                f"expected one of {sorted(_VALID_TRANSPORTS)}"
            )
        if transport == "stdio" and not entry.get("command"):
            raise ConfigMissing(
                f"MCP server {name!r} uses stdio transport but is missing required field 'command'"
            )
        if transport in ("http", "sse") and not entry.get("url"):
            raise ConfigMissing(
                f"MCP server {name!r} uses {transport} transport but is missing required field 'url'"
            )
        headers = {
            key: _interpolate_env(str(val), server=name, header=key)
            for key, val in entry.get("headers", {}).items()
        }
        servers.append(MCPServerConfig(
            name=name,
            transport=transport,
            command=entry.get("command", ""),
            args=list(entry.get("args", [])),
            url=entry.get("url", ""),
            headers=headers,
        ))
    return servers


def save_token(path: Path, url: str, token: str) -> None:
    """Write or update url+token, preserving other fields if config exists."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    existing: dict = {}
    if p.exists():
        with open(p, "rb") as f:
            existing = _tomli.load(f)
    existing["ava_url"] = url
    existing["ava_token"] = token
    with open(p, "wb") as f:
        tomli_w.dump(existing, f)
