# MCP HTTP/SSE Transport Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let AvaDex connect to remote MCP servers over Streamable HTTP and legacy SSE, in addition to the existing stdio transport.

**Architecture:** Add an explicit `transport` field to MCP server config entries (default `stdio`, so existing configs are untouched). Parse entries into a validated `MCPServerConfig` dataclass with `${ENV}` interpolation on header values. `MCPClient` gains transport params and selects the right SDK context manager (`stdio_client` / `streamablehttp_client` / `sse_client`) via a small `_open_transport` helper; everything after the connection is unchanged.

**Tech Stack:** Python 3.11+, `mcp` SDK 1.27.1 (already installed; ships all three client transports), `tomllib`, pytest. Tests run with `.venv/bin/python -m pytest`.

---

## File Structure

- `avadex/config.py` — add `MCPServerConfig` dataclass, `_parse_mcp_servers`, env interpolation; change `Config.mcp_servers` type.
- `avadex/tools/mcp.py` — add transport params to `MCPClient.__init__`, add `_open_transport` helper, use it in `start()`.
- `avadex/cli.py` — build `MCPClient` from `MCPServerConfig` attributes instead of dict keys.
- `tests/unit/test_config.py` — update existing dict-access test; add transport/validation/interpolation tests.
- `tests/integration/test_mcp.py` — add `_open_transport` selection test + `MCPClient` field-storage test.
- `README.md`, `CHANGELOG.md`, `pyproject.toml`, `avadex/__init__.py` — docs + version bump.

---

### Task 1: `MCPServerConfig` dataclass + stdio back-compat parse

**Files:**
- Modify: `avadex/config.py`
- Test: `tests/unit/test_config.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_config.py`:

```python
def test_mcp_stdio_entry_parses_to_dataclass(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('''
ava_url = "u"
ava_token = "t"

[[mcp_servers]]
name = "fs"
command = "npx"
args = ["-y", "server"]
''')
    cfg = load_config(p)
    s = cfg.mcp_servers[0]
    assert s.name == "fs"
    assert s.transport == "stdio"      # defaulted
    assert s.command == "npx"
    assert s.args == ["-y", "server"]
    assert s.url == ""
    assert s.headers == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_config.py::test_mcp_stdio_entry_parses_to_dataclass -v`
Expected: FAIL — `AttributeError: 'dict' object has no attribute 'name'`.

- [ ] **Step 3: Write minimal implementation**

In `avadex/config.py`, add `import os` and `import re` at the top (after `from pathlib import Path`). Add the dataclass above `class Config`:

```python
@dataclass
class MCPServerConfig:
    name: str
    transport: str = "stdio"
    command: str = ""
    args: list[str] = field(default_factory=list)
    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)
```

Change the `Config.mcp_servers` field annotation:

```python
    mcp_servers: list[MCPServerConfig] = field(default_factory=list)
```

Add the parser function below `load_config` (interpolation comes in Task 3; for now pass headers through unchanged):

```python
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
        servers.append(MCPServerConfig(
            name=name,
            transport=transport,
            command=entry.get("command", ""),
            args=list(entry.get("args", [])),
            url=entry.get("url", ""),
            headers=dict(entry.get("headers", {})),
        ))
    return servers
```

In `load_config`, change the `mcp_servers=` line inside the `Config(...)` constructor from:

```python
            mcp_servers=list(data.get("mcp_servers", [])),
```
to:
```python
            mcp_servers=_parse_mcp_servers(data.get("mcp_servers", [])),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_config.py::test_mcp_stdio_entry_parses_to_dataclass -v`
Expected: PASS.

- [ ] **Step 5: Fix the existing dict-access test**

In `tests/unit/test_config.py`, `test_load_full_config` currently ends with:

```python
    assert cfg.mcp_servers[0]["name"] == "fs"
```
Change it to:
```python
    assert cfg.mcp_servers[0].name == "fs"
```

- [ ] **Step 6: Run the full config suite**

Run: `.venv/bin/python -m pytest tests/unit/test_config.py -q`
Expected: PASS (all tests, including `test_save_token_preserves_other_fields` and `test_load_uses_defaults_for_unset` which checks `cfg.mcp_servers == []`).

- [ ] **Step 7: Commit**

```bash
git add avadex/config.py tests/unit/test_config.py
git commit -m "Parse MCP server entries into MCPServerConfig dataclass"
```

---

### Task 2: Validate required fields per transport

**Files:**
- Modify: `avadex/config.py` (the `_parse_mcp_servers` function from Task 1)
- Test: `tests/unit/test_config.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_config.py`:

```python
def test_mcp_http_requires_url(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('''
ava_url = "u"
ava_token = "t"

[[mcp_servers]]
name = "remote"
transport = "http"
''')
    with pytest.raises(ConfigMissing, match="url"):
        load_config(p)


def test_mcp_sse_requires_url(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('''
ava_url = "u"
ava_token = "t"

[[mcp_servers]]
name = "legacy"
transport = "sse"
''')
    with pytest.raises(ConfigMissing, match="url"):
        load_config(p)


def test_mcp_stdio_requires_command(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('''
ava_url = "u"
ava_token = "t"

[[mcp_servers]]
name = "local"
''')
    with pytest.raises(ConfigMissing, match="command"):
        load_config(p)


def test_mcp_bad_transport_raises(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('''
ava_url = "u"
ava_token = "t"

[[mcp_servers]]
name = "x"
transport = "carrier-pigeon"
url = "https://x"
''')
    with pytest.raises(ConfigMissing, match="transport"):
        load_config(p)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_config.py -k "requires or bad_transport" -v`
Expected: `test_mcp_bad_transport_raises` PASSES already (Task 1 added the transport check); the three `*_requires_*` tests FAIL (no field validation yet).

- [ ] **Step 3: Add field validation**

In `_parse_mcp_servers`, after computing `transport` and before appending, insert:

```python
        if transport == "stdio" and not entry.get("command"):
            raise ConfigMissing(
                f"MCP server {name!r} uses stdio transport but is missing required field 'command'"
            )
        if transport in ("http", "sse") and not entry.get("url"):
            raise ConfigMissing(
                f"MCP server {name!r} uses {transport} transport but is missing required field 'url'"
            )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_config.py -k "requires or bad_transport" -v`
Expected: all 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add avadex/config.py tests/unit/test_config.py
git commit -m "Validate required MCP fields per transport"
```

---

### Task 3: `${ENV}` interpolation on header values

**Files:**
- Modify: `avadex/config.py`
- Test: `tests/unit/test_config.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_config.py`:

```python
def test_mcp_header_env_interpolation(tmp_path, monkeypatch):
    monkeypatch.setenv("GH_MCP_TOKEN", "secret123")
    p = tmp_path / "config.toml"
    p.write_text('''
ava_url = "u"
ava_token = "t"

[[mcp_servers]]
name = "github"
transport = "http"
url = "https://mcp.example.com/mcp"
[mcp_servers.headers]
Authorization = "Bearer ${GH_MCP_TOKEN}"
''')
    cfg = load_config(p)
    assert cfg.mcp_servers[0].headers["Authorization"] == "Bearer secret123"


def test_mcp_header_missing_env_raises(tmp_path, monkeypatch):
    monkeypatch.delenv("GH_MCP_TOKEN", raising=False)
    p = tmp_path / "config.toml"
    p.write_text('''
ava_url = "u"
ava_token = "t"

[[mcp_servers]]
name = "github"
transport = "http"
url = "https://mcp.example.com/mcp"
[mcp_servers.headers]
Authorization = "Bearer ${GH_MCP_TOKEN}"
''')
    with pytest.raises(ConfigMissing, match="GH_MCP_TOKEN"):
        load_config(p)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_config.py -k "interpolation or missing_env" -v`
Expected: FAIL — `test_mcp_header_env_interpolation` returns the literal `"Bearer ${GH_MCP_TOKEN}"`; `test_mcp_header_missing_env_raises` does not raise.

- [ ] **Step 3: Implement interpolation**

In `avadex/config.py`, add near the top (after imports):

```python
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
            )
    return _ENV_RE.sub(repl, value)
```

In `_parse_mcp_servers`, replace the `headers=dict(entry.get("headers", {})),` line with a pre-built interpolated dict. Just before `servers.append(...)`, add:

```python
        headers = {
            key: _interpolate_env(str(val), server=name, header=key)
            for key, val in entry.get("headers", {}).items()
        }
```
and change the append's headers argument to `headers=headers,`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_config.py -k "interpolation or missing_env" -v`
Expected: both PASS.

- [ ] **Step 5: Run the full config suite**

Run: `.venv/bin/python -m pytest tests/unit/test_config.py -q`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add avadex/config.py tests/unit/test_config.py
git commit -m "Interpolate \${ENV} vars in MCP header values"
```

---

### Task 4: `MCPClient` transport params + `_open_transport` helper

**Files:**
- Modify: `avadex/tools/mcp.py`
- Test: `tests/integration/test_mcp.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/integration/test_mcp.py`:

```python
def test_mcp_client_stores_transport_fields():
    from avadex.tools.mcp import MCPClient
    c = MCPClient(
        name="remote", transport="http",
        url="https://mcp.example.com/mcp",
        headers={"Authorization": "Bearer x"},
    )
    assert c.transport == "http"
    assert c.url == "https://mcp.example.com/mcp"
    assert c.headers == {"Authorization": "Bearer x"}


def test_open_transport_selects_client_per_transport(monkeypatch):
    import mcp.client.stdio, mcp.client.sse, mcp.client.streamable_http
    from avadex.tools.mcp import MCPClient, _open_transport

    # _open_transport does `from mcp.client.X import Y` at call time, so patching
    # the source-module attribute is seen by the fresh import. Each stub returns
    # a sentinel instead of a real (network-opening) context manager.
    monkeypatch.setattr(mcp.client.stdio, "stdio_client", lambda params: "STDIO")
    monkeypatch.setattr(mcp.client.sse, "sse_client", lambda url, headers=None: "SSE")
    monkeypatch.setattr(mcp.client.streamable_http, "streamablehttp_client",
                        lambda url, headers=None: "HTTP")

    assert _open_transport(MCPClient(name="a", command="true")) == "STDIO"
    assert _open_transport(
        MCPClient(name="b", transport="http", url="https://h/mcp", headers={"X": "1"})
    ) == "HTTP"
    assert _open_transport(
        MCPClient(name="c", transport="sse", url="https://s/sse")
    ) == "SSE"


def test_open_transport_unknown_raises():
    from avadex.tools.mcp import MCPClient, _open_transport
    bad = MCPClient(name="x", transport="bogus", url="https://x")
    with pytest.raises(ValueError, match="bogus"):
        _open_transport(bad)
```

Note: each factory stub returns a sentinel string, so `_open_transport` does no
network I/O. The real `StdioServerParameters(...)` is still constructed for the
stdio case (cheap, no connection) before the patched `stdio_client` is called.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/integration/test_mcp.py -k "transport" -v`
Expected: FAIL — `MCPClient.__init__` rejects `transport=`/`url=`/`headers=`; `_open_transport` does not exist.

- [ ] **Step 3: Update `MCPClient.__init__`**

In `avadex/tools/mcp.py`, replace the existing constructor:

```python
    def __init__(self, name: str, command: str, args: list[str]):
        self.name = name
        self.command = command
        self.args = args
        self.is_healthy: bool = True
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._session = None  # mcp.ClientSession
        self._exit_stack = None
        self._tools_cache: list[dict] = []
```

with:

```python
    def __init__(self, name: str, transport: str = "stdio",
                 command: Optional[str] = None, args: Optional[list[str]] = None,
                 url: Optional[str] = None,
                 headers: Optional[dict[str, str]] = None):
        self.name = name
        self.transport = transport
        self.command = command or ""
        self.args = args or []
        self.url = url or ""
        self.headers = headers or {}
        self.is_healthy: bool = True
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._session = None  # mcp.ClientSession
        self._exit_stack = None
        self._tools_cache: list[dict] = []
```

- [ ] **Step 4: Add the `_open_transport` helper**

In `avadex/tools/mcp.py`, add this module-level function below the imports (above `class MCPClient`):

```python
def _open_transport(client: "MCPClient"):
    """Return the SDK async context manager for the client's transport.

    Calling the SDK client factory does not open a connection; the connection
    happens when the returned context manager is entered.
    """
    from mcp import StdioServerParameters
    from mcp.client.stdio import stdio_client
    from mcp.client.sse import sse_client
    from mcp.client.streamable_http import streamablehttp_client

    if client.transport == "stdio":
        return stdio_client(StdioServerParameters(command=client.command, args=client.args))
    if client.transport == "http":
        return streamablehttp_client(client.url, headers=client.headers or None)
    if client.transport == "sse":
        return sse_client(client.url, headers=client.headers or None)
    raise ValueError(f"unknown MCP transport {client.transport!r}")
```

- [ ] **Step 5: Use the helper in `start()`**

In `start()`'s nested `async def _setup()`, replace these lines:

```python
            params = StdioServerParameters(command=self.command, args=self.args)
            transport = await self._exit_stack.enter_async_context(stdio_client(params))
            read, write = transport
```

with:

```python
            transport = await self._exit_stack.enter_async_context(_open_transport(self))
            read, write = transport[0], transport[1]
```

Then remove the now-unused imports at the top of `start()`:

```python
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        from contextlib import AsyncExitStack
```

becomes:

```python
        from mcp import ClientSession
        from contextlib import AsyncExitStack
```

(`StdioServerParameters` and the transport clients are now imported inside `_open_transport`.)

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/integration/test_mcp.py -k "transport" -v`
Expected: all 3 PASS.

- [ ] **Step 7: Run the full MCP suite**

Run: `.venv/bin/python -m pytest tests/integration/test_mcp.py -q`
Expected: PASS. (`test_mcp_lists_tools_from_reference_server` runs only if `npx` is present; `test_mcp_client_initializes_healthy` uses the new signature with `command="true"` — still valid since `command` is the second positional/keyword param.)

- [ ] **Step 8: Commit**

```bash
git add avadex/tools/mcp.py tests/integration/test_mcp.py
git commit -m "Add HTTP/SSE transport selection to MCPClient"
```

---

### Task 5: Wire `MCPServerConfig` attributes in `cli.py`

**Files:**
- Modify: `avadex/cli.py:122-130`

- [ ] **Step 1: Update the startup loop**

In `avadex/cli.py`, replace:

```python
    mcp_clients = []
    for entry in cfg.mcp_servers:
        mc = MCPClient(name=entry["name"], command=entry["command"], args=entry.get("args", []))
        try:
            mc.start()
            mcp_clients.append(mc)
        except Exception as exc:
            log.warning("MCP server '%s' failed to start: %s", entry["name"], exc)
    register_mcp_tools(mcp_clients, registry)
```

with:

```python
    mcp_clients = []
    for s in cfg.mcp_servers:
        mc = MCPClient(name=s.name, transport=s.transport, command=s.command,
                       args=s.args, url=s.url, headers=s.headers)
        try:
            mc.start()
            mcp_clients.append(mc)
        except Exception as exc:
            log.warning("MCP server '%s' failed to start: %s", s.name, exc)
    register_mcp_tools(mcp_clients, registry)
```

- [ ] **Step 2: Run the full test suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS (no regressions; nothing else accesses `cfg.mcp_servers` as dicts).

- [ ] **Step 3: Commit**

```bash
git add avadex/cli.py
git commit -m "Build MCPClient from MCPServerConfig fields"
```

---

### Task 6: Docs, CHANGELOG, version bump

**Files:**
- Modify: `README.md`, `CHANGELOG.md`, `pyproject.toml:7`, `avadex/__init__.py:1`

- [ ] **Step 1: Update README MCP/config section**

Locate the MCP server configuration section in `README.md` (search for `mcp_servers`). Add documentation for the new fields and an example. Insert after the existing stdio example:

````markdown
MCP servers can also be reached over HTTP. Set `transport` to `"http"`
(Streamable HTTP, recommended) or `"sse"` (legacy) and provide a `url`.
A `[mcp_servers.headers]` table supplies request headers; values may reference
environment variables with `${VAR}` so secrets stay out of the config file:

```toml
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

`transport` defaults to `"stdio"`, so existing `command`/`args` entries are
unchanged. A `${VAR}` that is not set in the environment is a startup error.
````

- [ ] **Step 2: Add a CHANGELOG entry**

At the top of `CHANGELOG.md`, add a new version section (match the existing format in the file):

```markdown
## 0.2.3

### Added
- MCP servers can now be reached over **Streamable HTTP** (`transport = "http"`)
  and legacy **SSE** (`transport = "sse"`), in addition to stdio. Remote servers
  accept a `[mcp_servers.headers]` table with `${ENV_VAR}` interpolation for auth.
```

- [ ] **Step 3: Bump the version**

In `pyproject.toml` line 7, change `version = "0.2.2"` to `version = "0.2.3"`.
In `avadex/__init__.py` line 1, change `__version__ = "0.2.2"` to `__version__ = "0.2.3"`.

(Use `0.3.0` instead if the user designates this a minor feature release.)

- [ ] **Step 4: Run the full suite once more**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add README.md CHANGELOG.md pyproject.toml avadex/__init__.py
git commit -m "Document MCP HTTP/SSE transport; bump to 0.2.3"
```

---

## Self-Review

**Spec coverage:**
- Both HTTP + SSE transports → Task 4 (`_open_transport` handles all three).
- Explicit `transport` field, default stdio → Task 1.
- Validation (name/transport/command/url) → Tasks 1 & 2.
- `headers` table + `${ENV}` interpolation → Task 3.
- `MCPClient` Approach A + helper → Task 4.
- cli.py wiring → Task 5.
- Error handling: config-time `ConfigMissing` (Tasks 1–3), startup warning (existing, preserved Task 5), runtime health-flip (unchanged).
- Testing: config unit tests (Tasks 1–3), `_open_transport`/field-storage tests (Task 4); live HTTP integration test intentionally out of scope per spec.
- Docs + release → Task 6.

**Placeholder scan:** No TBD/TODO; every code step shows full code; every command shows expected output.

**Type consistency:** `MCPServerConfig` fields (`name`, `transport`, `command`, `args`, `url`, `headers`) are used identically in Tasks 1, 4, 5. `_parse_mcp_servers`, `_interpolate_env`, `_open_transport` signatures match all call sites. `MCPClient.__init__` keyword names (`transport`/`command`/`args`/`url`/`headers`) match both the cli.py call (Task 5) and the tests (Task 4).
