# Changelog

All notable changes to AvaDex are recorded here. The project follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.5.1] — 2026-05-29

### Added
- Startup now logs the number of skills loaded, matching the existing
  `Loaded N MCP server(s) from ./.mcp.json` line. Format:
  `Loaded N skill(s) from global` / `from workdir` /
  `(N global, N workdir)` when both sources are present. Goes to stderr.
  Suppressed when no skills are found.

## [0.5.0] — 2026-05-29

### Added
- **Headless agent mode** for scripting and CI: `avadex --prompt "TEXT" [--model NAME]`
  runs one agent turn (no REPL), writes only the final assistant answer to
  stdout, and exits (errors to stderr; exit 0 on `end_turn`, non-zero
  otherwise). The agent's internal tool-use loop iterates as normal — MCP
  servers, file/bash tools, etc. — capped by `max_iterations` (default 50).
  Tool prompts auto-approve since there's no human to ask. `--model` is a
  general model override that also works in REPL mode. See README "Headless
  / scripted use".

## [0.4.1] — 2026-05-28

### Added
- Headless agent mode: `avadex --prompt "TEXT" [--model NAME]` runs one agent
  turn and exits, with only the final assistant answer written to stdout
  (errors to stderr, exit 0 on `end_turn` otherwise non-zero). The agent's
  internal tool-use loop still iterates as normal — MCP servers and built-in
  tools are all in play — and tool prompts auto-approve since there's no
  human to ask. `--model` overrides the model in both headless and REPL
  mode. Adds `HeadlessRenderer` to `avadex.renderer`.

## [0.4.0] — 2026-05-27

### Changed
- System prompt now steers the agent to answer domain/company questions
  (e.g. "what do you know about Syntec X") from the knowledge Ava injects into
  context (the `## Relevant knowledge from Ava` block) instead of grepping the
  local working directory with file tools. Previously the agent treated such
  questions as local file searches, grepped the (unrelated) project folder,
  and missed the knowledge base entirely.

## [0.3.0] — 2026-05-27

### Added
- Hybrid context management so sessions run far longer before losing context.
  When usage crosses a configurable high-water mark, AvaDex first runs a
  deterministic **dedup** pass — stubbing superseded `read_file` results,
  removing denied tool calls, and truncating large tool outputs (errors are
  kept) — then, if still over budget, **compacts** older turns into a single
  summary via the session model, preserving goals, key facts/data, decisions,
  and pending next steps. The existing FIFO prune remains as a final backstop.
  Context is now refit at the top of every agent iteration, so compaction can
  fire mid-task. New `config.toml` keys: `context_compaction_threshold` (0.8),
  `context_large_output_tokens` (1000), `context_keep_recent` (6).

## [0.2.12] — 2026-05-27

### Changed
- Agent iteration cap raised from 25 to 50 and exposed as `max_iterations` in
  `config.toml`, so multi-step tasks (e.g. paginating then writing a file) no
  longer abort mid-task. Repeat-detection still guards genuine loops.

## [0.2.11] — 2026-05-27

### Changed
- Larger token budget for coding sessions: `max_context_tokens` 3500 → 16000 and
  `max_response_tokens` 2048 → 4096; both now configurable in `config.toml`.

## [0.2.10] — 2026-05-26

### Changed
- System prompt now tells the model to render requested tables/lists from tool
  results (not just describe them), page through paginated results before
  answering "all", and reply in the user's language.

## [0.2.9] — 2026-05-26

### Fixed
- MCP tool names are sanitized to valid function-call identifiers (no dots or
  hyphens) so models can reproduce them — fixes "unknown tool" failures on
  namespaced MCP tools.

## [0.2.8] — 2026-05-26

### Fixed
- MCP server start failures now log their real cause (ExceptionGroups unwrapped,
  `repr` for empty-message errors such as a connect `TimeoutError`) instead of a
  blank message.

## [0.2.7] — 2026-05-26

### Changed
- Reworded the "tool call returned as text" warning so it no longer asserts the
  model lacks tool support; it suggests re-pulling the model, updating Ollama, or
  switching with `/model`.

## [0.2.6] — 2026-05-26

### Added
- Clear feedback when the selected model can't use tools: warns when a model
  emits a tool call as plain text (so nothing executes), and turns Ollama's
  "does not support tools" error into an actionable "switch with `/model`"
  message.

## [0.2.5] — 2026-05-26

### Added
- Skill loader: AvaDex discovers `SKILL.md` playbooks from `~/.config/avadex/skills/`
  and the working directory's `./skills/` (workdir wins on name clash), lists them
  in the system prompt, and exposes an auto-allowed `load_skill` tool the agent
  calls on demand. Independent of MCP server loading.

## [0.2.4] — 2026-05-26

### Added
- Per-directory MCP config: a `.mcp.json` (Claude Code format) in the working
  directory loads only those servers for that run, replacing the global
  `mcp_servers`. A sibling `.env` resolves `${VAR}` header secrets, wins over the
  process environment, and is scoped to MCP auth only.

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
