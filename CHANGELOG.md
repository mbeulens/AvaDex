# Changelog

All notable changes to AvaDex are recorded here. The project follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.3] — 2026-05-25

### Added
- MCP servers can now be reached over **Streamable HTTP** (`transport = "http"`)
  and legacy **SSE** (`transport = "sse"`), in addition to stdio. Remote servers
  accept a `[mcp_servers.headers]` table with `${ENV_VAR}` interpolation for auth.

## [0.2.0] — 2026-05-19

First minor release. Triples the tool surface, adds polish and safety,
closes every issue filed during the v0.1 series.

### Added

#### Tools
- `glob` — find files by pattern, sorted, capped at 200 results.
- `grep_files` — Python-regex search with structured `path:lineno:line` output.
- `web_fetch` — HTTP GET with 100 KB body cap, follows redirects.
- `multi_edit` — apply several edits to one file atomically (validate-all-then-apply).
- `todo_write` / `todo_read` — session-scoped task tracking (planning).
- `bash_bg` / `bash_output` / `kill_bash` / `bash_list` — long-running shell
  processes the model can start, query, and terminate.

#### REPL
- Welcome banner on startup: ASCII brand, version, cwd, current model, hints.
- ANSI color in the renderer (cyan tool calls, green success, red errors,
  dim chrome). Respects `NO_COLOR` and TTY detection.
- `/model` slash command: shows a numbered list, then a bare digit picks
  (`/model` → `2`). Also `/model <N>`, `/model <name>`, `/model refresh`.
- Multi-line input: Enter inserts a newline, `;` + Enter or Esc-Enter submits.
- Spinner during the blocking Ava request so the silent wait stops feeling
  like a hang.
- Initial model auto-resolves from Ava's `/api/v1/models` if `default_model`
  isn't set in config (previously hardcoded `"gemma4"`).

#### Operations
- `--debug` flag now wires Python `logging` to
  `~/.local/state/avadex/debug.log` (rotating, 1 MB × 5 files).
- System prompt rewritten to tell the model to reach for `bash` boldly
  (gh, git, curl, systemctl, etc.) instead of declining tasks it has no
  dedicated tool for.

### Changed
- `avadex login` removed; replaced with `avadex set-key` (Ava's
  `/api/v1/messages` uses a static API key, not session tokens).
- `Config.default_model` defaults to `""` (empty) which means "ask Ava on
  startup". Set it explicitly to override.
- `ToolDefinition` gains an `is_available` callable; tools whose backing
  client is unhealthy (e.g. crashed MCP server) are filtered from
  `ToolRegistry.schemas()` / `names()` / `dispatch()`.
- README adds a Security section about unsandboxed tool execution.

### Fixed
- `AvaError` / `TokenExpired` no longer crash the REPL — caught in
  `run_turn` and surfaced via the renderer.
- `load_config` now raises `ConfigMissing` (with the missing field name)
  instead of a bare `KeyError` for incomplete `config.toml` files.
- `bash` tool's `timeout` argument is now clamped to `MAX_BASH_TIMEOUT`
  (600s). Previously documented but not enforced.
- `AvaClient.messages` rejects non-Anthropic HTTP 200 responses
  (`{"error": ...}` etc.) with a useful `AvaError` instead of silently
  rendering an empty turn.
- MCP server crash is now contained: the client is marked unhealthy on
  the first `call_tool` exception, a one-time warning is emitted, and
  its tools disappear from subsequent turns' schema.
- `tests/unit/test_smoke.py` no longer requires a `pip install -e .`
  after every patch bump (now checks `__version__` format only).

### Ava (server-side companion)
- Added `GET /api/v1/models` endpoint (`server.py` commit `03c60c6`,
  Ava version `0.1.1`) with API-key auth, returning the list and default
  model. AvaDex's `/model` command depends on it.

## [0.1.x] — 2026-05-18

Initial implementation. Skeleton through 0.1.48 across ~50 commits
covering the spec, the per-task TDD plan, the implementation itself,
and the long tail of post-v1-review fixes. See `git log v0.1.48` for
the per-commit detail; the consolidated narrative starts here at 0.2.0.
