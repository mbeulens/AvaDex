# Per-directory `.mcp.json` + `.env` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When AvaDex starts in a directory containing a `.mcp.json` (Claude Code format), load ONLY those MCP servers, resolving header secrets from a sibling `.env` that wins over the process environment but is scoped to MCP auth only.

**Architecture:** A new `avadex/mcp_workdir.py` module discovers `cwd/.mcp.json`, parses an optional `cwd/.env` into a dict (no `os.environ` mutation), translates Claude's `mcpServers` map into the raw-dict shape `config._parse_mcp_servers` already consumes, and parses it with a merged env (`os.environ` overlaid by `.env`). `config._parse_mcp_servers`/`_interpolate_env` gain an `env` param so the same validation + `${ENV}` interpolation is reused. `cli.run_repl` calls `resolve_mcp_servers(cfg, Path.cwd())` instead of reading `cfg.mcp_servers` directly.

**Tech Stack:** Python 3.11+, stdlib `json`, pytest. Tests run with `.venv/bin/python -m pytest`. No new dependency.

---

## File Structure

- `avadex/config.py` — thread an `env` mapping param through `_interpolate_env` and `_parse_mcp_servers` (default `os.environ`).
- `avadex/mcp_workdir.py` — NEW. `load_dotenv`, `claude_to_raw`, `resolve_mcp_servers`, plus `MCP_JSON_FILENAME`/`DOTENV_FILENAME` constants.
- `avadex/cli.py` — call `resolve_mcp_servers`; print a one-line notice when the workdir file is used.
- `tests/unit/test_config.py` — tests for the new `env` param.
- `tests/unit/test_mcp_workdir.py` — NEW. Tests for all three module functions.
- `README.md`, `CHANGELOG.md`, `pyproject.toml`, `avadex/__init__.py` — docs + version bump.

---

### Task 1: Thread an `env` mapping through config interpolation

**Files:**
- Modify: `avadex/config.py:63-111`
- Test: `tests/unit/test_config.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_config.py`:

```python
def test_parse_mcp_servers_honors_env_mapping():
    from avadex.config import _parse_mcp_servers
    raw = [{
        "name": "x", "transport": "http", "url": "https://h",
        "headers": {"Authorization": "Bearer ${TOK}"},
    }]
    servers = _parse_mcp_servers(raw, env={"TOK": "fromdict"})
    assert servers[0].headers["Authorization"] == "Bearer fromdict"


def test_parse_mcp_servers_env_defaults_to_os_environ(monkeypatch):
    from avadex.config import _parse_mcp_servers
    monkeypatch.setenv("TOK", "fromenv")
    raw = [{
        "name": "x", "transport": "http", "url": "https://h",
        "headers": {"Authorization": "Bearer ${TOK}"},
    }]
    servers = _parse_mcp_servers(raw)  # no env -> falls back to os.environ
    assert servers[0].headers["Authorization"] == "Bearer fromenv"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_config.py -k "env_mapping or env_defaults" -v`
Expected: `test_parse_mcp_servers_honors_env_mapping` FAILS (`_parse_mcp_servers` takes no `env` kwarg → TypeError). The defaults test may pass already.

- [ ] **Step 3: Add the `env` param to `_interpolate_env`**

In `avadex/config.py`, replace the current `_interpolate_env` (lines 63-73):

```python
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
```

with:

```python
def _interpolate_env(value: str, *, server: str, header: str, env) -> str:
    def repl(match: re.Match) -> str:
        var = match.group(1)
        try:
            return env[var]
        except KeyError:
            raise ConfigMissing(
                f"MCP server {server!r} header {header!r} references "
                f"${{{var}}} but environment variable {var!r} is not set"
            ) from None
    return _ENV_RE.sub(repl, value)
```

- [ ] **Step 4: Add the `env` param to `_parse_mcp_servers`**

In `avadex/config.py`, change the signature line:

```python
def _parse_mcp_servers(raw: list[dict]) -> list[MCPServerConfig]:
```
to:
```python
def _parse_mcp_servers(raw: list[dict], *, env=None) -> list[MCPServerConfig]:
    if env is None:
        env = os.environ
```

(Insert the two `if env is None` lines as the first body lines, before `servers: list[MCPServerConfig] = []`.)

Then update the headers comprehension inside the loop to pass `env`:

```python
        headers = {
            key: _interpolate_env(str(val), server=name, header=key)
            for key, val in entry.get("headers", {}).items()
        }
```
becomes:
```python
        headers = {
            key: _interpolate_env(str(val), server=name, header=key, env=env)
            for key, val in entry.get("headers", {}).items()
        }
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_config.py -q`
Expected: all PASS (the existing interpolation tests still pass because `env` defaults to `os.environ`).

- [ ] **Step 6: Commit**

```bash
git add avadex/config.py tests/unit/test_config.py
git commit -m "Thread env mapping through MCP header interpolation"
```

---

### Task 2: `load_dotenv` in new `avadex/mcp_workdir.py`

**Files:**
- Create: `avadex/mcp_workdir.py`
- Test: `tests/unit/test_mcp_workdir.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_mcp_workdir.py`:

```python
import pytest


def test_load_dotenv_parses_keys_quotes_comments_export(tmp_path):
    from avadex.mcp_workdir import load_dotenv
    p = tmp_path / ".env"
    p.write_text(
        "FOO=bar\n"
        "# a comment\n"
        "\n"
        "export BAZ=qux\n"
        'QUOTED="hello world"\n'
        "SINGLE='abc'\n"
        "noequalsline\n"
    )
    env = load_dotenv(p)
    assert env == {
        "FOO": "bar",
        "BAZ": "qux",
        "QUOTED": "hello world",
        "SINGLE": "abc",
    }


def test_load_dotenv_missing_file_returns_empty(tmp_path):
    from avadex.mcp_workdir import load_dotenv
    assert load_dotenv(tmp_path / "nope.env") == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_mcp_workdir.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'avadex.mcp_workdir'`.

- [ ] **Step 3: Create the module with `load_dotenv`**

Create `avadex/mcp_workdir.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_mcp_workdir.py -v`
Expected: both PASS.

- [ ] **Step 5: Commit**

```bash
git add avadex/mcp_workdir.py tests/unit/test_mcp_workdir.py
git commit -m "Add load_dotenv parser to mcp_workdir module"
```

---

### Task 3: `claude_to_raw` format translation

**Files:**
- Modify: `avadex/mcp_workdir.py`
- Test: `tests/unit/test_mcp_workdir.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_mcp_workdir.py`:

```python
def test_claude_to_raw_maps_type_to_transport():
    from avadex.mcp_workdir import claude_to_raw
    data = {"mcpServers": {
        "remote": {"type": "http", "url": "https://h", "headers": {"A": "B"}},
        "local": {"command": "npx", "args": ["-y", "srv"]},  # no type -> stdio
    }}
    by_name = {r["name"]: r for r in claude_to_raw(data)}
    assert by_name["remote"]["transport"] == "http"
    assert by_name["remote"]["url"] == "https://h"
    assert by_name["remote"]["headers"] == {"A": "B"}
    assert by_name["local"]["transport"] == "stdio"
    assert by_name["local"]["command"] == "npx"
    assert by_name["local"]["args"] == ["-y", "srv"]


def test_claude_to_raw_empty_returns_empty_list():
    from avadex.mcp_workdir import claude_to_raw
    assert claude_to_raw({}) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_mcp_workdir.py -k claude_to_raw -v`
Expected: FAIL — `ImportError: cannot import name 'claude_to_raw'`.

- [ ] **Step 3: Add `claude_to_raw`**

Append to `avadex/mcp_workdir.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_mcp_workdir.py -k claude_to_raw -v`
Expected: both PASS.

- [ ] **Step 5: Commit**

```bash
git add avadex/mcp_workdir.py tests/unit/test_mcp_workdir.py
git commit -m "Add Claude .mcp.json -> raw-dict translation"
```

---

### Task 4: `resolve_mcp_servers` (workdir-replaces-global + .env merge)

**Files:**
- Modify: `avadex/mcp_workdir.py`
- Test: `tests/unit/test_mcp_workdir.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_mcp_workdir.py`:

```python
HTTP_JSON = (
    '{"mcpServers": {"r": {"type": "http", "url": "https://h",'
    ' "headers": {"Authorization": "Bearer ${TOK}"}}}}'
)


def test_resolve_no_mcp_json_returns_global(tmp_path):
    from avadex.mcp_workdir import resolve_mcp_servers
    from avadex.config import Config, MCPServerConfig
    cfg = Config(ava_url="u", ava_token="t",
                 mcp_servers=[MCPServerConfig(name="g", command="x")])
    result = resolve_mcp_servers(cfg, tmp_path)
    assert result is cfg.mcp_servers
    assert [s.name for s in result] == ["g"]


def test_resolve_loads_workdir_servers(tmp_path):
    from avadex.mcp_workdir import resolve_mcp_servers
    from avadex.config import Config
    (tmp_path / ".mcp.json").write_text(
        '{"mcpServers": {"remote": {"type": "http", "url": "https://h"}}}'
    )
    cfg = Config(ava_url="u", ava_token="t")
    result = resolve_mcp_servers(cfg, tmp_path)
    assert len(result) == 1
    assert result[0].name == "remote"
    assert result[0].transport == "http"
    assert result[0].url == "https://h"


def test_resolve_dotenv_wins_over_os_environ(tmp_path, monkeypatch):
    from avadex.mcp_workdir import resolve_mcp_servers
    from avadex.config import Config
    monkeypatch.setenv("TOK", "from_os")
    (tmp_path / ".env").write_text("TOK=from_dotenv\n")
    (tmp_path / ".mcp.json").write_text(HTTP_JSON)
    cfg = Config(ava_url="u", ava_token="t")
    result = resolve_mcp_servers(cfg, tmp_path)
    assert result[0].headers["Authorization"] == "Bearer from_dotenv"


def test_resolve_dotenv_only_var(tmp_path, monkeypatch):
    from avadex.mcp_workdir import resolve_mcp_servers
    from avadex.config import Config
    monkeypatch.delenv("TOK", raising=False)
    (tmp_path / ".env").write_text("TOK=only_dotenv\n")
    (tmp_path / ".mcp.json").write_text(HTTP_JSON)
    cfg = Config(ava_url="u", ava_token="t")
    result = resolve_mcp_servers(cfg, tmp_path)
    assert result[0].headers["Authorization"] == "Bearer only_dotenv"


def test_resolve_malformed_json_raises(tmp_path):
    from avadex.mcp_workdir import resolve_mcp_servers
    from avadex.config import Config, ConfigMissing
    (tmp_path / ".mcp.json").write_text("{ not valid json ")
    cfg = Config(ava_url="u", ava_token="t")
    with pytest.raises(ConfigMissing):
        resolve_mcp_servers(cfg, tmp_path)


def test_resolve_missing_var_raises(tmp_path, monkeypatch):
    from avadex.mcp_workdir import resolve_mcp_servers
    from avadex.config import Config, ConfigMissing
    monkeypatch.delenv("TOK", raising=False)
    (tmp_path / ".mcp.json").write_text(HTTP_JSON)
    cfg = Config(ava_url="u", ava_token="t")
    with pytest.raises(ConfigMissing, match="TOK"):
        resolve_mcp_servers(cfg, tmp_path)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_mcp_workdir.py -k resolve -v`
Expected: FAIL — `ImportError: cannot import name 'resolve_mcp_servers'`.

- [ ] **Step 3: Add imports and `resolve_mcp_servers`**

In `avadex/mcp_workdir.py`, change the top imports from:

```python
from __future__ import annotations
from pathlib import Path
```
to:
```python
from __future__ import annotations
import json
import os
from pathlib import Path

from avadex.config import (
    Config,
    MCPServerConfig,
    ConfigMissing,
    _parse_mcp_servers,
)
```

Then append at the end of the file:

```python
def resolve_mcp_servers(cfg: Config, cwd: Path) -> list[MCPServerConfig]:
    """If `cwd/.mcp.json` exists, load ONLY its servers (Claude format),
    interpolating headers with `os.environ` overlaid by `cwd/.env` (.env wins).
    Otherwise return `cfg.mcp_servers` unchanged.

    The merged env is used only here; it is never written into os.environ.
    """
    mcp_path = cwd / MCP_JSON_FILENAME
    if not mcp_path.exists():
        return cfg.mcp_servers
    try:
        data = json.loads(mcp_path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        raise ConfigMissing(f"could not read {mcp_path}: {exc}") from exc
    env = {**os.environ, **load_dotenv(cwd / DOTENV_FILENAME)}  # .env wins
    return _parse_mcp_servers(claude_to_raw(data), env=env)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_mcp_workdir.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add avadex/mcp_workdir.py tests/unit/test_mcp_workdir.py
git commit -m "Add resolve_mcp_servers: workdir .mcp.json replaces global, .env wins"
```

---

### Task 5: Wire `resolve_mcp_servers` into `cli.py`

**Files:**
- Modify: `avadex/cli.py` (import line region near line 7-15, and the MCP startup block near lines 122-131)

- [ ] **Step 1: Add the import**

In `avadex/cli.py`, after the line:

```python
from avadex.config import save_token, load_config, ConfigMissing
```
add:
```python
from avadex.mcp_workdir import resolve_mcp_servers
```

- [ ] **Step 2: Replace the MCP startup block**

In `avadex/cli.py`, replace:

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

with:

```python
    try:
        mcp_specs = resolve_mcp_servers(cfg, Path.cwd())
    except ConfigMissing as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if (Path.cwd() / ".mcp.json").exists():
        print(f"Loaded {len(mcp_specs)} MCP server(s) from ./.mcp.json",
              file=sys.stderr)

    mcp_clients = []
    for s in mcp_specs:
        mc = MCPClient(name=s.name, transport=s.transport, command=s.command,
                       args=s.args, url=s.url, headers=s.headers)
        try:
            mc.start()
            mcp_clients.append(mc)
        except Exception as exc:
            log.warning("MCP server '%s' failed to start: %s", s.name, exc)
    register_mcp_tools(mcp_clients, registry)
```

- [ ] **Step 3: Verify no regressions + wiring is present**

Run the full suite:
`.venv/bin/python -m pytest -q`
Expected: all PASS (172 + the new mcp_workdir/config tests).

Confirm the wiring (no leftover direct `cfg.mcp_servers` iteration in the startup loop):
`grep -n "resolve_mcp_servers\|for s in" avadex/cli.py`
Expected: shows `mcp_specs = resolve_mcp_servers(cfg, Path.cwd())` and `for s in mcp_specs:`.

Note: `run_repl` is not unit-tested directly (it constructs the live client/REPL); the delegated `resolve_mcp_servers` is fully covered by `tests/unit/test_mcp_workdir.py`, and the full-suite run guards against import/wiring regressions.

- [ ] **Step 4: Commit**

```bash
git add avadex/cli.py
git commit -m "Load workdir .mcp.json servers in run_repl"
```

---

### Task 6: Docs, CHANGELOG, version bump

**Files:**
- Modify: `README.md`, `CHANGELOG.md`, `pyproject.toml`, `avadex/__init__.py`

- [ ] **Step 1: Add a README section**

In `README.md`, find the Configuration section's MCP content (search for `transport = "sse"` — there is an HTTP/SSE example ending with a paragraph that begins "`transport` defaults to `"stdio"`..."). Immediately AFTER that paragraph, add:

````markdown
### Per-directory MCP servers (`.mcp.json`)

If the directory you launch AvaDex from contains a `.mcp.json` (the same format
Claude Code uses), AvaDex loads **only** those servers for that run and ignores
the `mcp_servers` in your global config. This lets you keep a small, task-scoped
subset of servers per working directory.

```json
{
  "mcpServers": {
    "github": {
      "type": "http",
      "url": "https://mcp.example.com/mcp",
      "headers": { "Authorization": "Bearer ${GITHUB_MCP_TOKEN}" }
    }
  }
}
```

`type` maps to AvaDex's transport (`stdio` / `http` / `sse`, defaulting to
`stdio`). A sibling `.env` file in the same directory supplies values for
`${VAR}` references in headers:

```
GITHUB_MCP_TOKEN=ghp_xxx
```

The `.env` **wins** over the process environment, and its values are used
**only** for MCP header auth — they are not exported to commands the agent runs.
A malformed `.mcp.json` or an unset `${VAR}` is a startup error.
````

- [ ] **Step 2: Add a CHANGELOG entry**

At the top of `CHANGELOG.md` (above the `## [0.2.3]` entry), matching the existing `## [x.y.z] — date` + `### Added` style:

```markdown
## [0.2.4] — 2026-05-25

### Added
- Per-directory MCP config: a `.mcp.json` (Claude Code format) in the working
  directory loads only those servers for that run, replacing the global
  `mcp_servers`. A sibling `.env` resolves `${VAR}` header secrets, wins over the
  process environment, and is scoped to MCP auth only.
```

- [ ] **Step 3: Bump the version**

In `pyproject.toml`, change `version = "0.2.3"` to `version = "0.2.4"`.
In `avadex/__init__.py`, change `__version__ = "0.2.3"` to `__version__ = "0.2.4"`.

- [ ] **Step 4: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add README.md CHANGELOG.md pyproject.toml avadex/__init__.py
git commit -m "Document per-directory .mcp.json/.env; bump to 0.2.4"
```

---

## Self-Review

**Spec coverage:**
- Workdir replaces global → Task 4 (`resolve_mcp_servers` returns `cfg.mcp_servers` only when no `.mcp.json`).
- Claude format translation → Task 3 (`claude_to_raw`, `type`→`transport`).
- `.env` wins over process env → Task 4 (`{**os.environ, **load_dotenv(...)}`), tested.
- `.env` scoped to MCP auth only → Tasks 1 + 4 (merged env passed as a param; `os.environ` never mutated; `load_dotenv` does not touch environ).
- `.env` parser → Task 2 (`load_dotenv`).
- cli wiring + notice → Task 5.
- Error handling: malformed JSON (Task 4), bad transport/missing field (reused validation, Task 4 via `_parse_mcp_servers`), missing `${VAR}` (Task 4 test), tolerated `.env` lines (Task 2 `noequalsline` case), per-server start failure unchanged (Task 5 preserves try/except).
- Docs + release → Task 6.

**Placeholder scan:** No TBD/TODO; every code step has full code; every command states expected output.

**Type consistency:** `load_dotenv(path) -> dict[str,str]`, `claude_to_raw(dict) -> list[dict]`, `resolve_mcp_servers(cfg, cwd) -> list[MCPServerConfig]` used identically across tasks and in cli.py. `_parse_mcp_servers(raw, *, env=None)` and `_interpolate_env(..., env=...)` signatures match between Task 1 (definition) and Task 4 (call). Constants `MCP_JSON_FILENAME`/`DOTENV_FILENAME` defined in Task 2, used in Task 4. cli.py uses `mcp_specs` consistently.
