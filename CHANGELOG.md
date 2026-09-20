# Changelog

All notable changes to AvaDex are recorded here. The project follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.3.0] — 2026-09-21

Minor release: a headless run keeps its task, or says so. 1.2.0 stopped
context trimming from dropping the task; this finishes the job for the case
where it was already gone, restoring it instead of sending a request Ava
refuses, and records what happened. Collects 1.2.1 – 1.2.2.

### Fixed
- **A request could still go out with no user text (1.2.1).** 1.2.0's anchor
  guard was a silent no-op when the anchor was already missing:
  `_anchor_index` returns `None`, and `None not in {…}` is always true, so
  pruning proceeded unprotected. Ava then rejected the request with a 400 and
  the unattended run died. `prune`/`drop_oldest` now test for `None`
  explicitly, and — since neither can invent a user message — `AgentLoop`
  re-anchors: if the conversation has no user text before a request (including
  the context-overflow retry), the task is put back, with a warning to the
  user and the message shape (roles and block types, no content) in the debug
  log. How the task went missing is still unknown: simulated runs with
  Conductor's settings, large and errored MCP results, compaction and pruning
  all keep it. Reported by Syntec Conductor with a verified repro.
- With `--debug`, the re-anchor warning is followed by the **full
  conversation** in the debug log (image payloads excluded), so a recurrence
  can be diagnosed from one run. Without `--debug` only roles and block types
  are recorded. README now warns that `--debug` can write conversation content
  to disk. (1.2.2)

## [1.2.0] — 2026-09-20

Minor release: two failures that unattended runs could not see. A long run
kept its task through context trimming, and a model that writes a tool call
out as text now fails the run instead of finishing it having done nothing.
Both came out of Syntec Conductor's production runs. Collects 1.1.1 – 1.1.3.

### Fixed
- **Long runs no longer lose their task after compaction (1.1.1).** When the
  recent tool results alone exceeded the context budget, compaction was
  followed by pruning, and pruning dropped the oldest message first: the
  compaction summary, which was the only user text left. The next request was
  just tool calls and tool results. Models served with Ollama's `qwen3.8`
  renderer reject that with a 500 "no user query found in messages", and any
  model would have lost its task. Pruning now always keeps the most recent
  user message with text (the task or the summary). The retry after Ava
  reports a context overflow used `messages[4:]`, which could drop the task
  and split a tool call from its result. It now uses the same rules
  (`drop_oldest`). Found by Syntec Conductor; diagnosed on the host by
  ava-deploy.

- **A tool call written as markup is caught too (1.1.3).** AvaDex flagged a
  model that emitted a tool call as JSON text, but not Qwen's
  `<function=name>…</function>` form, or `<tool_call>` / `<function_call>`
  wrappers. Such a run ended `end_turn` with exit 0, so a caller read it as a
  completed step although nothing ran. These now raise the same error and exit
  1. Markup inside a code fence is ignored, so explaining the syntax is still
  fine. Reported by Syntec Conductor, which saw a specialist "call"
  `syntec_forms_form_list` in prose and build the next step on work that never
  happened.

### Docs (1.1.2)
- README "Known limitations" explains that trimming keeps the task, and
  why losing it was worse than the error qwen3.8 raised.

## [1.1.0] — 2026-09-19

Minor release: AvaDex as an unattended runtime. Built for Syntec Conductor,
which drives AvaDex headless for Ava-hosted models and now uses it as a
planning orchestrator as well as for specialists. Everything is additive;
without the new flags, behaviour is unchanged. Collects patches 1.0.1 – 1.0.12.

### Added
- **`--allow-tools LIST`** — the caller names exactly which tools a run may
  use. Everything else is left out of the schemas sent to the model and
  refused at dispatch (`ToolRegistry.restrict`), so a hallucinated tool name
  can't get through. Entries: a tool name, `mcp__<server>` (all tools of an
  MCP server), `mcp__<server>__<tool>`, or the exposed `<server>_<tool>` name.
  It fails closed: an entry matching no available tool exits 2 before Ava is
  called, which also catches an MCP server that failed to start. Refusals go
  to stderr, and the system prompt names the allowed tools. Without the flag,
  behaviour is unchanged. (1.0.1, 1.0.2)
- **`--output-format json`** — headless runs print one result object: the
  answer, errors, summed `usage` (input/output tokens over every Ava request,
  including tool round-trips, retries and compaction), `usage_complete`,
  `requested_model` vs the `model`(s) Ava actually ran, request count,
  duration and `permission_denials`. Shaped after Claude Code's envelope.
  (1.0.3, 1.0.4)
- **`--ignore-user-config`** — with `--config`, skip the invoking user's
  `~/.config/avadex/allowlist.toml` and `~/.config/avadex/skills/`, so a run
  uses only the given config and the workdir. With no allowlist file at all,
  `/allow` rules stay in memory for the session. (1.0.5)
- **`avadex models [--json]`** — list the models Ava's `GET /api/v1/models`
  accepts, with the default marked. `--json` includes the key's `ava` policy
  block when Ava sends one. (1.0.6, 1.0.8)
- **Key-privacy pass-through and `--require-private` (1.0.8).** Ava ≥ 0.4.6
  echoes the calling key's policy (`"ava": {key, private, rag, retained}`) on
  every response. The JSON envelope now carries the last one as `ava`, plus
  `ava_changed` when it differed, appeared or disappeared during the run.
  `--require-private` fails closed: it checks `GET /api/v1/models` before the
  prompt is sent, and every response including compaction calls, aborting
  before that response's tool calls run. Only an explicit `private: true`
  passes. Prompted by a key that was flipped to shared on the server after
  a client's startup check had already passed.
- **Tool transcript in the JSON envelope (1.0.11).** `transcript` lists
  every tool call with its tool, MCP server, input and output. Output is
  verbatim and untruncated; image data is replaced by type and size. Each
  entry's `status` is `ok`, `error` (flagged, not dropped), `no_result`
  (started, nothing came back) or `not_run` (requested, but the run aborted
  first). This lets a caller check facts against what the tools returned
  instead of the model's summary. Requested by Syntec Conductor, which does
  this with Claude and Codex runs.

### Changed
- MCP tools now record their server and MCP-side name, so they can be
  selected per server.
- `HeadlessRenderer` keeps every error message (`errors`); `errored` is
  derived from it.

### Fixed (1.0.9)
- **MCP was dead on a fresh install.** `mcp>=1.0` resolved to SDK 2.x, which
  renamed `streamablehttp_client`, so every HTTP MCP server failed to start
  (found by Syntec Conductor). The dependency is now capped at `mcp>=1.0,<2`.
  A new test imports the real SDK clients without monkeypatching, so an SDK
  rename fails the suite instead of shipping. A second regression test pins
  the fail-closed path Conductor hit: with `--allow-tools mcp__<server>` and
  a server that won't start, AvaDex exits 2 without calling Ava.

### Docs (1.0.7, 1.0.10, 1.0.12)
- README documents the new flags, the config precedence table and
  `avadex models`, and fixes three errors: MCP tools are exposed as
  `<server>_<tool>` (not `<server>.<tool>`); `config.toml` needs
  `ava_url`/`ava_token`, and keys come from Ava's API-key admin (optionally
  private) rather than only the env key; `--debug` logs to
  `~/.local/state/avadex/debug.log`, not stderr.
- README "Listing models" now says that a working tool call doesn't mean the
  model uses the result correctly, and how to design data questions around
  that: numbers come from tools, existence checks use filters, and deciding
  facts are checked in code. Prompted by Syntec Conductor seeing a model
  count 195 forms as 194 and then 205. (1.0.10)
- README and package description: "powered by the Syntec Ava assistant".
  (1.0.12)

### Notes
- Real token counts need Ava ≥ 0.4.2 (live since Ava 0.4.5). Against older
  servers `usage_complete` is `false`.

## [1.0.0] — 2026-09-16

First stable release. No behavior changes over 0.8.0 — this marks the CLI
surface as settled and puts it under semantic versioning.

### Stability
- The following are now public API, and breaking changes to them require a
  major bump: the `avadex` CLI flags (`--config`, `--prompt`, `--model`,
  `--yes`/`-y`, `--workdir`, `--debug`) and the `set-key` subcommand; the
  `config.toml` keys; the allowlist file format and its two locations
  (`~/.config/avadex/allowlist.toml` and `<workdir>/.avadex/allowlist.toml`);
  the skill layout (`skills/<name>/SKILL.md`) and `.mcp.json` discovery;
  and the process exit codes (0 success, 1 agent error, 2 configuration error).
- Built-in tool names and their arguments are part of the agent contract and
  are likewise covered.

### Notes
- Requires Ava ≥ 0.4.0 for `attach_image` (vision); every other feature works
  against older Ava servers.
- Linux only, and there is still no sandbox — see Security in the README.

## [0.8.0] — 2026-09-16

### Added
- `--workdir PATH` flag and a matching `workdir` key in `config.toml`: choose
  the directory AvaDex works in instead of always using the launch directory.
  Precedence is flag > config > current directory. `~` is expanded and a
  relative path resolves against the directory you ran the command from, since
  resolution happens before the chdir. AvaDex `chdir`s into the workdir at
  startup, so project `skills/`, `.mcp.json` + `.env`, `bash`, `glob`,
  `grep_files` and relative file paths all follow it. An unusable workdir
  exits 2 with a clear message.
- Project-local allowlist at `<workdir>/.avadex/allowlist.toml`. Its rules are
  merged with (not substituted for) the global
  `~/.config/avadex/allowlist.toml`, global first, so a project file can only
  widen what is permitted. When a workdir is in play, `/allow` appends new
  rules there instead of the global file, creating it on demand.

### Changed
- `PermissionManager` takes an optional second allowlist path. The global and
  workdir rule lists are tracked separately so a save rewrites only its own
  file — adding a project rule can no longer flatten global rules into it, or
  the reverse. Single-argument construction is unchanged.

### Fixed
- Version drift between `pyproject.toml`, `avadex/__init__.py` and the REPL
  banner is now caught by tests, so a release can't bump one and leave the
  banner showing the old number.

## [0.7.0] — 2026-07-02

### Added
- `attach_image` tool: give the agent a local image (jpg/png/gif/webp/bmp,
  ≤5 MB) to visually read — gauges, dials, meters, screenshots, text, tables.
  The model calls it with a path (`~` expanded); the file is base64-encoded
  into an Anthropic image block and carried to Ava, which routes the request
  to a vision-capable model. Works the same in the REPL and headless
  (`--prompt`). Auto-approved (read-only tier). Requires Ava ≥ 0.4.0 and a
  vision-capable model installed on the Ava server.

### Changed
- `ToolResult.content` may now be a list of content blocks (not just a string),
  so tools can return images. The context-window token estimator counts image
  payloads at a flat nominal cost instead of their raw base64 length, so an
  attached image no longer blows the context budget and gets pruned away.

## [0.6.0] — 2026-05-29

### Added
- `--yes` / `-y` flag for autonomous REPL sessions: auto-approves every tool
  call — writes included — with no per-action confirmation prompt. Mirrors the
  auto-approval that headless `--prompt` already applies, so the same agent can
  run unattended interactively. Prompter selection is now centralized in
  `_select_prompter(prompt, auto_approve)`: auto-approve when either `--prompt`
  or `--yes` is set, otherwise the interactive terminal prompter.
  **Note:** `--yes` removes the human checkpoint before destructive/write tools
  (`s_prt_create`, `bash`, `write_file`, …); use it deliberately.

## [0.5.2] — 2026-05-29

### Changed
- Skill-index preamble in the system prompt is now an unambiguous mandate:
  *"When the user's request matches a skill below, you MUST call `load_skill`
  FIRST, before any other tool — including MCP tools that look like a direct
  shortcut."* Plus a short rationale about raw tool schemas not enforcing the
  rules the skill body holds. The old preamble (*"…BEFORE acting"*) was
  routinely outweighed by the model's bias toward direct tool use when an MCP
  tool matched the task; the strengthened phrasing eliminates the worst-shape
  filter calls (operator-wrapper / dotted-key hallucinations) even on runs
  where the model still skips the explicit `load_skill` call.

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
