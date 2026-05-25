# HTTP / SSE transport for MCP tools — Design

**Date:** 2026-05-25
**Status:** Approved, ready for implementation plan

## Problem

AvaDex can connect to MCP servers over **stdio only**. `MCPClient` hardcodes
`StdioServerParameters` + `stdio_client`, and config entries only describe
`name`/`command`/`args`. This excludes the growing set of remote MCP servers
that speak HTTP. We want AvaDex to also connect to remote servers over the
modern **Streamable HTTP** transport and the legacy **SSE** transport.

The installed SDK (`mcp` 1.27.1) already ships `mcp.client.streamable_http.streamablehttp_client`
and `mcp.client.sse.sse_client`, so no new dependency is required.

## Decisions

1. **Transports:** support all three — `stdio` (existing), `http` (Streamable
   HTTP), and `sse` (legacy). Streamable HTTP is the spec-recommended transport;
   SSE is kept for compatibility with older remote servers.
2. **Config:** an explicit `transport` field per server entry, defaulting to
   `"stdio"` so every existing config keeps working untouched.
3. **Auth:** a per-server `headers` table with `${ENV_VAR}` interpolation, so
   secrets live in the environment rather than plaintext config.

## Approach

**Approach A — single parameterized `MCPClient`.** Everything in `MCPClient`
*after* the transport connects (background asyncio loop, session `initialize`,
`list_tools`, `call_tool` health-flipping, `stop()`'s cancel-scope handling) is
transport-agnostic. Only the async context manager that yields `(read, write)`
differs between transports. So we parameterize that one piece rather than
introducing subclasses (over-engineered for 3 fixed cases) or leaving the
selection inline. The selection lives in a small `_open_transport` helper for
testability.

## Components

### 1. Config schema (`avadex/config.py`)

Introduce a structured entry type, replacing the raw-dict entries:

```python
@dataclass
class MCPServerConfig:
    name: str
    transport: str = "stdio"          # "stdio" | "http" | "sse"
    command: str = ""                 # stdio only
    args: list[str] = field(default_factory=list)
    url: str = ""                     # http/sse only
    headers: dict[str, str] = field(default_factory=dict)  # http/sse only
```

`Config.mcp_servers` changes type from `list[dict]` to `list[MCPServerConfig]`.

A new `_parse_mcp_servers(raw: list[dict]) -> list[MCPServerConfig]` validates
each entry and raises `ConfigMissing` (reusing the existing friendly-error path
caught in `cli.py`) on:

- missing `name`
- `transport` not in `{stdio, http, sse}`
- `stdio` without `command`
- `http`/`sse` without `url`

`headers` is parsed for every entry but only *used* by `http`/`sse`. For
`stdio` it is ignored (documented; not an error — keeps validation minimal).

### 2. Env interpolation (`avadex/config.py`)

Header values pass through `${VAR}` → `os.environ[VAR]` substitution:

```python
_ENV_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
```

A missing env var raises `ConfigMissing` naming the server, header, and the
variable, so an unset token fails loudly at startup rather than mid-session.
Interpolation is scoped to header **values** only — not `url` or `command` —
to keep the surface tight.

### 3. `MCPClient` (`avadex/tools/mcp.py`)

Constructor gains transport params. Existing keyword call sites
(`MCPClient(name=..., command=..., args=...)`) keep working because `transport`
defaults to `"stdio"`:

```python
def __init__(self, name, transport="stdio", command=None, args=None,
             url=None, headers=None):
```

A module-level helper selects the transport context manager:

```python
def _open_transport(spec):
    if spec.transport == "stdio":
        return stdio_client(StdioServerParameters(command=spec.command, args=spec.args))
    if spec.transport == "http":
        return streamablehttp_client(spec.url, headers=spec.headers or None)
    if spec.transport == "sse":
        return sse_client(spec.url, headers=spec.headers or None)
    raise ValueError(f"unknown transport {spec.transport!r}")
```

In `start()`'s `_setup` coroutine, the connection step becomes:

```python
transport = await self._exit_stack.enter_async_context(_open_transport(self))
read, write = transport[0], transport[1]   # http yields a 3-tuple; slice covers all
```

Streamable HTTP yields a 3-tuple `(read, write, get_session_id)`; stdio and SSE
yield 2-tuples. Slicing `transport[0], transport[1]` handles all three. Nothing
else in `MCPClient` changes.

### 4. Wiring (`avadex/cli.py`)

The startup loop switches from dict access to attribute access:

```python
for s in cfg.mcp_servers:
    mc = MCPClient(name=s.name, transport=s.transport, command=s.command,
                   args=s.args, url=s.url, headers=s.headers)
    try:
        mc.start()
        mcp_clients.append(mc)
    except Exception as exc:
        log.warning("MCP server '%s' failed to start: %s", s.name, exc)
```

The existing `try/except` already logs a warning and skips on failure, so remote
connection errors (network, 401, bad URL) degrade gracefully like a stdio server
that won't spawn.

## Data flow

```
config.toml  --load_config-->  Config.mcp_servers: list[MCPServerConfig]
                                  (validated, env-interpolated)
   |
   v
cli.run_repl  --per entry-->  MCPClient(transport=...)  --start()-->  _open_transport
   |                                                                     |
   |                                                stdio_client / streamablehttp_client / sse_client
   v                                                                     |
register_mcp_tools  <--list_tools--  ClientSession.initialize  <--(read, write)
```

## Error handling

- **Config-time (load):** missing fields, bad transport, unset env var →
  `ConfigMissing` → clean exit 2 via the existing handler at `cli.py:113`.
- **Startup (connect):** network / auth / timeout → warning logged, server
  skipped, REPL continues.
- **Runtime (tool call):** unchanged — first failure flips `is_healthy=False`,
  warns once, hides the server's tools for the session.

## Testing

- **Unit (`tests/unit/test_config.py`):**
  - `transport` defaults to `stdio` when omitted
  - validation errors: missing `name`; bad `transport`; `stdio` without
    `command`; `http`/`sse` without `url`
  - env interpolation: success path; missing-env-var raises `ConfigMissing`
    naming the variable
- **Unit (`tests/integration/test_mcp.py` or unit):**
  - `MCPClient` stores `transport`/`url`/`headers` correctly
  - `_open_transport` returns the correct SDK client per transport (without
    connecting / no network)
- **Integration:** keep the existing stdio reference-server test. An HTTP/SSE
  live test (running `@modelcontextprotocol/server-everything` in HTTP mode)
  is optional and skipped by default, since binding a port is flaky in CI.
  Transport-opening correctness is covered by the unit test on `_open_transport`
  plus SDK delegation.

## Docs & release

- **README:** extend the MCP/config section to document `transport`, `url`,
  `headers`, and `${ENV}` interpolation, with the Streamable HTTP example.
- **CHANGELOG:** new entry describing HTTP/SSE MCP transport support.
- **Version:** patch bump per the per-edit convention (or a minor bump if the
  user designates this a user-facing feature release).

## Config example

```toml
# stdio (unchanged; transport defaults to "stdio")
[[mcp_servers]]
name = "local"
command = "npx"
args = ["-y", "@modelcontextprotocol/server-everything"]

# Streamable HTTP with bearer auth from the environment
[[mcp_servers]]
name = "github"
transport = "http"
url = "https://mcp.example.com/mcp"
[mcp_servers.headers]
Authorization = "Bearer ${GITHUB_MCP_TOKEN}"

# legacy SSE
[[mcp_servers]]
name = "legacy"
transport = "sse"
url = "https://old.example.com/sse"
```

## Out of scope (YAGNI)

- WebSocket transport (`websockets` not installed).
- OAuth flows / token refresh (the SDK's `auth` param is left at default;
  static bearer headers cover the common case).
- Env interpolation in `url`/`command`.
- A live HTTP integration test in the default suite.
