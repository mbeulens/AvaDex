# Per-directory `.mcp.json` + `.env` for MCP servers — Design

**Date:** 2026-05-25
**Status:** Approved, ready for implementation plan

## Problem

AvaDex loads its MCP servers from the global `~/.config/avadex/config.toml`
(`mcp_servers`). The user wants to drive AvaDex as a task-scoped agent: drop a
small, curated set of MCP servers next to the work, per invocation. They already
have MCP fleets in **Claude Code's `.mcp.json` format** (a `mcpServers` map with
`type`/`url`/`headers`, e.g. a 308-server Syntec enterprise package) and prefer
to keep using that format, paired with a `.env` for the auth token.

Goal: when AvaDex starts in a directory containing a `.mcp.json`, load **only**
those servers (Claude format), resolving header secrets from a sibling `.env`.

## Decisions

1. **Workdir replaces global.** If `./.mcp.json` exists, use *only* its servers
   and ignore `config.toml`'s `mcp_servers`. If it does not exist, behave exactly
   as today. This gives a clean "exact subset per call" model.
2. **`.env` wins over the process environment.** When a variable is defined in
   both `./.env` and `os.environ`, the `.env` value is used — each task folder
   fully controls its own tokens.
3. **`.env` is scoped to MCP auth only.** Its values are used solely to resolve
   `${VAR}` in MCP server headers; they are NOT written into `os.environ`, so the
   agent's bash tool and any subprocess it spawns do not see them. Smallest blast
   radius.
4. **Claude format reuse.** Claude `.mcp.json` entries translate into the same
   raw-dict shape `config._parse_mcp_servers` already consumes, so all existing
   validation and `${ENV}` interpolation are reused — only a translation step and
   an `env` mapping are new.

## Approach

**Approach A — new `avadex/mcp_workdir.py` module.** The workdir-discovery,
dotenv-parsing, and Claude-format-translation concerns get their own unit, keeping
`config.py` focused on "load the global TOML config." No new runtime dependency:
`.env` files in this use are simple `KEY=VALUE`, so a ~15-line parser suffices
(rather than adding `python-dotenv`).

## Components

### `avadex/mcp_workdir.py`

```python
MCP_JSON_FILENAME = ".mcp.json"
DOTENV_FILENAME = ".env"


def load_dotenv(path: Path) -> dict[str, str]:
    """Parse a simple KEY=VALUE .env into a dict. Missing file -> {}.
    Skips blank lines and '#' comments, tolerates a leading 'export ',
    splits on the first '=', strips matching surrounding quotes. Does NOT
    mutate os.environ."""


def claude_to_raw(mcp_json: dict) -> list[dict]:
    """Translate Claude's mcpServers map into the raw-dict shape that
    config._parse_mcp_servers expects: dict key -> 'name', 'type' ->
    'transport' (default 'stdio'), and command/args/url/headers carried
    through."""


def resolve_mcp_servers(cfg: Config, cwd: Path) -> list[MCPServerConfig]:
    """If cwd/.mcp.json exists, load ONLY its servers (Claude format),
    interpolating headers with os.environ overlaid by cwd/.env (.env wins).
    Otherwise return cfg.mcp_servers unchanged."""
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

The module reuses the package-internal `config._parse_mcp_servers` and
(transitively) `_interpolate_env`. They stay underscore-prefixed and are imported
intra-package (small diff; same package).

### `avadex/config.py` changes

- `_interpolate_env(value, *, server, header, env)` — add an `env` mapping param.
- `_parse_mcp_servers(raw, *, env=None)` — add `env`; use
  `env if env is not None else os.environ` and pass it into `_interpolate_env`.
- `load_config` is unchanged (keeps the `os.environ` default), so the global
  config path behaves exactly as today. Scoping `.env` to MCP auth only falls out
  of this: the merged env lives in the passed dict, never in `os.environ`.

### `avadex/cli.py` wiring

```python
from avadex.mcp_workdir import resolve_mcp_servers
...
try:
    mcp_specs = resolve_mcp_servers(cfg, Path.cwd())
except ConfigMissing as exc:
    print(str(exc), file=sys.stderr)
    return 2

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

When the workdir file is used, print a one-line notice — `Loaded N MCP server(s)
from ./.mcp.json` — since large fleets take noticeable time to spin up. To decide
whether to print it (without changing `resolve_mcp_servers`'s `list` return type),
cli.py checks `(Path.cwd() / ".mcp.json").exists()` itself and prints the notice
with `len(mcp_specs)` when true. The redundant existence check is intentional and
cheap; it keeps the resolver's contract a plain list.

## Data flow

```
cwd/.mcp.json present?
  no  -> cfg.mcp_servers (from config.toml, os.environ interpolation)
  yes -> json.loads(.mcp.json)
           -> claude_to_raw  (type->transport, key->name)
           -> _parse_mcp_servers(raw, env = os.environ + .env)   (.env wins)
           -> list[MCPServerConfig]
  -> cli loop -> MCPClient(transport=...) -> _open_transport -> SDK
```

## Error handling

- Malformed / unreadable `.mcp.json` → `ConfigMissing` → exit 2 (loud, not a
  silent empty fleet — it is the user's task set).
- Bad `transport` / missing `url` / missing `command` in an entry → reuses
  existing `_parse_mcp_servers` validation → `ConfigMissing` → exit 2.
- A `${VAR}` referenced in a header but absent from both `os.environ` and `.env`
  → existing `_interpolate_env` raises `ConfigMissing` → exit 2.
- Malformed `.env` lines (no `=`) → tolerated (skipped).
- Per-server connection failure at `start()` → unchanged: warning logged, server
  skipped, REPL continues.

## Testing (`tests/unit/test_mcp_workdir.py`)

- `load_dotenv`: `KEY=VALUE`; single/double quoted values; `#` comment lines;
  blank lines; `export ` prefix; missing file → `{}`.
- `claude_to_raw`: `type` → `transport`; missing `type` → `stdio`;
  command/args/url/headers carried through; dict key becomes `name`.
- `resolve_mcp_servers` (with `tmp_path` as cwd):
  - no `.mcp.json` → returns `cfg.mcp_servers` unchanged
  - `.mcp.json` present → returns its servers (count + names + transport)
  - **`.env` wins**: same var in `os.environ` (monkeypatched) and `.env` → header
    resolves to the `.env` value
  - `.env`-only var → header interpolates correctly
  - malformed JSON → `ConfigMissing`
  - `${VAR}` missing everywhere → `ConfigMissing`
- `config.py`: `_parse_mcp_servers(env={...})` honors the passed mapping rather
  than `os.environ`.

## Docs & release

- **README:** new "Per-directory MCP servers (`.mcp.json`)" section — Claude
  format example, `.env` pairing, replaces-global semantics, `.env`-wins,
  auth-only scope.
- **CHANGELOG:** entry for workdir `.mcp.json`/`.env` support.
- **Version:** patch bump to 0.2.4 (minor if the user designates it a feature
  release).

## Out of scope (YAGNI)

- Merging workdir servers with global ones (decision: replace).
- Exporting `.env` into `os.environ` / subprocess visibility (decision:
  MCP-auth-only).
- `python-dotenv` dependency (hand-rolled parser suffices).
- Upward directory search / nested `.mcp.json` discovery — only the immediate
  cwd is checked.
- Auto-capping the number of servers started (the user curates the file).
- Claude stdio `env` per-server field (AvaDex has no equivalent; not needed for
  the HTTP use case).
