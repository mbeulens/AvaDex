# AvaDex — Local CLI Agent Powered by Ava

**Status:** Design approved, awaiting implementation plan
**Date:** 2026-05-18
**Author:** Martijn Beulens (Syntec) with Claude

## Summary

AvaDex is a Python CLI that turns Ana's self-hosted Ava assistant into a local
agent for system administration and coding tasks on the user's own machine.
It opens an interactive REPL, talks to Ava's existing Anthropic-compatible
`/api/v1/messages` endpoint, executes tool calls locally (file edits, shell
commands, MCP servers), and gates risky actions behind an allowlist-based
permission model.

The goal of v1 is "Claude Code, but driven by my own Gemma4 on my own box,"
constrained by what Ava's current API can deliver.

## Goals

- Single-user CLI for personal daily use.
- REPL-style agentic loop over Ava's `/api/v1/messages`.
- Built-in tools: `read_file`, `write_file`, `edit_file`, `bash`.
  (Web search and RAG access are deferred — see "Open questions for v2"; Ava
  doesn't expose standalone endpoints for them today, and auto-RAG already
  runs server-side on every `/api/v1/messages` call.)
- MCP server support (stdio transport) for third-party tools.
- Allowlist + interactive prompt for permissioned actions.
- Long-lived token auth, set up once via `avadex login`.
- No changes to Ava's codebase. Work within current API constraints.

## Non-goals (v1)

- Multi-user / SaaS. AvaDex is per-machine, per-user.
- Streaming token output. Ava's tool-calling endpoint is non-streaming today.
- Cross-session conversation persistence / resume.
- Sub-agents, TodoWrite, slash-command extensibility beyond a handful of
  built-in slashes.
- Sandboxing or VM isolation. AvaDex runs with the user's privileges.
- Voice, TTS, GUI. Terminal only.
- Windows-native support. Linux first (matches the user's environment).

## Constraints (from Ava's current API)

Verified by reading `~/Development/Local/Ava/server.py`:

- **Non-streaming.** `/api/v1/messages` returns a full Anthropic-format
  response after a single `ollama_local.chat()` call.
- **Tight context window.** Hardcoded `num_ctx=4096` per request.
- **Auto-RAG injection.** Every request appends top-3 ChromaDB hits from the
  Syntec corpus to the system prompt based on the last user message.
- **Auth.** `Authorization: Bearer <session-token>` from Ava's `/login`.
- **Models.** `gemma4` is the only routinely-available model.

No Ava patches required. AvaDex absorbs the constraints by: rendering a
spinner during the non-streaming wait, conservatively pruning history to
`max_context_tokens=3500` (leaving headroom for the auto-RAG insertion and
Ava's reply), and tolerating Syntec-corpus RAG bleed in the system prompt —
sometimes useless, occasionally helpful, never load-bearing.

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                  avadex (Python CLI)                │
│                                                     │
│  ┌──────────────┐                                   │
│  │ prompt_toolkit│ ← user input, history, ANSI UI  │
│  │     REPL      │                                   │
│  └──────┬────────┘                                   │
│         │ user message                               │
│  ┌──────▼──────────────────────────────────────┐    │
│  │              Agent Loop                      │    │
│  │  1. Build request (msgs + tools)             │    │
│  │  2. POST /api/v1/messages → Ava              │    │
│  │  3. Parse content blocks                     │    │
│  │  4. If tool_use → permission check           │    │
│  │     → execute → tool_result → goto 1         │    │
│  │  5. If end_turn → print, await user          │    │
│  └─┬────────────────────┬───────────────┬─────┘    │
│    │                    │                │           │
│  ┌─▼──────────┐  ┌──────▼──────┐  ┌─────▼────────┐ │
│  │ Built-in   │  │ Permission  │  │ MCP Client   │ │
│  │ tools      │  │  Manager    │  │ (stdio)      │ │
│  └────────────┘  └─────────────┘  └──────┬───────┘ │
│                                          │          │
│                                   ┌──────▼───────┐ │
│                                   │ MCP servers  │ │
│                                   │ (subprocs)   │ │
│                                   └──────────────┘ │
└─────────────────────┬───────────────────────────────┘
                      │ HTTPS + Bearer token
                      ▼
            ┌──────────────────┐
            │ Ava server       │
            │ /api/v1/messages │
            │ → Gemma4/Ollama  │
            └──────────────────┘
```

Single Python process, ~7 modules. MCP servers are child processes spoken to
over stdio using the official `mcp` Python SDK.

## Components

### `avadex/cli.py` — entry point
Argparse-based. Subcommands:
- `avadex login` — interactive setup of Ava URL, username, password. Hits
  Ava's `/login`, stores returned token in `~/.config/avadex/config.toml`.
- `avadex` (default) — start the REPL.
- `avadex --config <path>` — override config location.
- `avadex --debug` — verbose logging to `~/.local/state/avadex/debug.log`.

### `avadex/config.py` — config loader
TOML at `~/.config/avadex/config.toml`. Schema:

```toml
ava_url = "https://ava.example.com"
ava_token = "..."
default_model = "gemma4"
max_context_tokens = 3500  # safety margin under Ava's 4096 num_ctx
system_prompt_path = ""    # optional; defaults to bundled prompt

[[mcp_servers]]
name = "filesystem"
command = "npx"
args = ["-y", "@modelcontextprotocol/server-filesystem", "/home/beuner"]
```

(Per-call `bash` timeout lives inside the tool itself, default 30s; not in
config.)

Loaded once at startup. No hot reload in v1.

### `avadex/ava_client.py` — HTTP client
Single public method:

```python
def messages(
    system: str,
    messages: list[dict],
    tools: list[dict],
    max_tokens: int = 2048,
) -> AnthropicResponse: ...
```

Wraps `requests` (or `httpx`). Handles auth header, JSON encoding. On HTTP 401
raises `TokenExpired` (REPL surfaces "run `avadex login`"). Other HTTP errors
raise `AvaError` with status + body excerpt. No automatic retries.

### `avadex/repl.py` — interactive loop
`prompt_toolkit` `PromptSession`:
- Multi-line input (submit on Esc-Enter or `;` at end of line).
- History file `~/.local/state/avadex/history`.
- ANSI rendering: tool calls prefixed with `●`, output indented two spaces,
  errors in red.
- Slash commands (v1 minimum):
  - `/exit` — quit
  - `/clear` — wipe conversation history
  - `/tools` — list available tools (built-in + MCP)
  - `/allow <tool> <pattern>` — add a permission allowlist rule manually
  - (No `/cost` in v1 — Ava returns zero in the `usage` field today.)

### `avadex/agent_loop.py` — the core
Owns the conversation list and runs turns.

```python
def run_turn(user_text: str) -> None:
    messages.append({"role": "user", "content": user_text})
    context_manager.prune(messages, max_tokens=config.max_context_tokens)

    for iteration in range(MAX_ITERATIONS):  # default 25
        response = ava_client.messages(system, messages, tool_schemas)

        if response.stop_reason != "tool_use":
            render(response.content)
            messages.append({"role": "assistant", "content": response.content})
            return

        messages.append({"role": "assistant", "content": response.content})
        tool_results = []
        for block in tool_use_blocks(response.content):
            tool_results.append(execute(block))
        messages.append({"role": "user", "content": tool_results})

    handle_runaway()
```

Context manager: estimates tokens via a heuristic (chars/4) with 1.2× safety
factor. When over budget, drops oldest user/assistant pair. Never drops the
system prompt; never separates an assistant `tool_use` from its matching
`tool_result`.

### `avadex/permissions.py` — permission manager
Allowlist at `~/.config/avadex/allowlist.toml`:

```toml
[[rules]]
tool = "bash"
pattern = "ls *"

[[rules]]
tool = "bash"
pattern = "git status"

[[rules]]
tool = "read_file"
pattern = "*"   # all reads auto-allowed
```

`check(tool_name, args)` returns one of `auto_allow`, `prompt`, `auto_deny`.
Built-in defaults:
- `read_file`, `web_search`, `rag_search` → `auto_allow` (read-only).
- `write_file`, `edit_file`, `bash` → `prompt` unless matched by allowlist.

Interactive prompt UI: `[y]es / [n]o / [a]lways`. On `a`, user picks a glob
pattern; the rule is appended to allowlist.toml.

### `avadex/tools/builtin.py`
Four tools, each a `(args: dict) -> ToolResult` function plus a JSON-schema:

| Name          | Behavior                                                          |
|---------------|-------------------------------------------------------------------|
| `read_file`   | Read full file, return contents. Path validation; size cap (1 MB) |
| `write_file`  | Overwrite file. Creates parent dirs                               |
| `edit_file`   | Exact old_string → new_string replacement; errors if not unique   |
| `bash`        | `subprocess.run`, captures stdout+stderr, default 30s timeout     |

Tool names and schemas intentionally mirror Claude Code's so the model has
prior familiarity. `web_search` and `rag_search` are deferred — Ava has no
standalone endpoints for them, and auto-RAG already fires on every
`/api/v1/messages` request.

### `avadex/tools/mcp.py` — MCP integration
Uses the official `mcp` Python SDK. On REPL startup, for each `[[mcp_servers]]`
config entry: spawn subprocess with `command`+`args`, perform MCP handshake
over stdio, call `list_tools()`, cache schemas. Each MCP tool gets prefixed
with the server name (e.g. `filesystem.read_file`) to avoid collisions with
built-ins.

On server crash mid-call: mark unhealthy, exclude from next request's tool
list, log to debug. Don't attempt automatic restart in v1.

### `avadex/tools/registry.py` — dispatch
Merges built-in + MCP tool schemas into one list passed to Ava. Resolves a
`tool_use.name` to its handler.

## Data flow (one user turn)

1. User types `"add a healthcheck endpoint to server.py"`.
2. Agent loop appends to conversation. Context manager prunes if needed.
3. POST to Ava:
   ```json
   {
     "model": "gemma4",
     "system": "<system prompt>",
     "messages": [...full history...],
     "tools": [<all tool schemas>],
     "max_tokens": 2048
   }
   ```
4. Ava returns Anthropic-format response.
   - `stop_reason: "end_turn"` → render content, return to prompt.
   - `stop_reason: "tool_use"` → continue.
5. For each `tool_use` block:
   - `permissions.check(name, input)` → allow / prompt / deny.
   - Render `● tool_name(args summary)`.
   - Dispatch via registry. Wrap result as `tool_result`.
6. Append assistant message (with tool_use blocks) and one user message
   containing all tool_results. Loop to step 3.
7. On Ctrl-C: abort in-flight request or subprocess, discard partial assistant
   message, return to prompt with conversation intact.

Conversation is in-memory only. `/clear` resets. No cross-session resume in v1.

## Error handling

| Failure                          | Behavior                                              |
|----------------------------------|-------------------------------------------------------|
| Network / DNS / timeout to Ava   | Print error, return to prompt. No retry.              |
| HTTP 401                         | Print "run `avadex login`". Return to prompt.         |
| HTTP 5xx                         | Print status + body excerpt. Conversation preserved.  |
| Malformed JSON response          | Log full body to debug.log. Print parse error.        |
| Built-in tool exception          | Catch, return `is_error: true tool_result`. Loop on.  |
| `bash` timeout                   | Kill subprocess. Return `is_error: true` + partial.   |
| `edit_file` ambiguous old_string | Structured error so model can retry with more context.|
| MCP server crash                 | Mark unhealthy. Exclude from next tool list.          |
| Permission denial                | `is_error: true, content: "denied by user"`.          |
| Context overflow from Ava        | Drop 2 oldest pairs, retry once. Then abort turn.     |
| 25 iterations without end_turn   | Inject "stop, summarize" user msg. One more call.     |
| Same output 3 turns in a row     | Abort with "repeated output detected".                |
| Config missing                   | Print "run `avadex login`" and exit.                  |
| MCP server fails to start        | Warn and continue without it.                         |

**Principle:** never silently swallow errors. Never crash the REPL on a
recoverable failure. Tool failures feed back to the model; infra failures
abort the turn but keep the session alive.

## Testing strategy

- **Unit tests** (`pytest`, pure logic):
  - `permissions.check()` with table-driven cases.
  - Context-manager pruning: synthesize conversations of known token counts,
    assert what gets dropped and that tool_use/tool_result pairs stay together.
  - Anthropic block parsing: text/tool_use mixes, malformed blocks.
  - `edit_file` matching, including the not-unique error path.

- **Integration tests against a fake Ava** (`pytest` + a local aiohttp server):
  - Scripted Anthropic responses.
  - Full agent loops: text-only turn, single-tool turn, multi-tool turn,
    error response, runaway detection.
  - Assert exact request bodies AvaDex sends.

- **Tool sandbox tests**: built-in tools tested against `tmp_path`. `bash`
  timeout tested with `sleep`.

- **MCP integration**: one test using the reference `mcp-server-everything`
  server to verify schema fetching + dispatch end-to-end.

- **Manual smoke** (`tests/smoke.md` checklist, run before each release):
  login, a coding task, a system task, a permission prompt, Ctrl-C abort.

- **Out of scope**: model quality (that's a Gemma4/Ava concern), pixel-perfect
  rendering, performance benchmarks.

## Project layout

```
AvaDex/
├── avadex/
│   ├── __init__.py
│   ├── cli.py
│   ├── config.py
│   ├── ava_client.py
│   ├── repl.py
│   ├── agent_loop.py
│   ├── permissions.py
│   └── tools/
│       ├── __init__.py
│       ├── builtin.py
│       ├── mcp.py
│       └── registry.py
├── tests/
│   ├── unit/
│   ├── integration/
│   └── smoke.md
├── docs/
│   └── superpowers/
│       └── specs/
│           └── 2026-05-18-avadex-design.md
├── pyproject.toml
└── README.md
```

Packaging: `pyproject.toml` with `hatchling`. Console script entry point
`avadex = "avadex.cli:main"`. Installable via `pipx install .`.

## Open questions for v2

Not blocking v1, but worth noting:

- Ask Ana for opt-out of auto-RAG injection on `/api/v1/messages`
  (currently spends ~500 tokens per request on Syntec docs that AvaDex
  doesn't want).
- Ask Ana for streaming on `/api/v1/messages`.
- Ask Ana for configurable `num_ctx` (the hardcoded 4096 will bite as soon as
  AvaDex starts editing real codebases).
- Ask Ana for standalone `/api/search` (SearXNG proxy) and
  `/api/rag/search` (ChromaDB query) endpoints so AvaDex can expose
  `web_search` and `rag_search` tools.
- Cross-session conversation resume (`avadex resume <id>`).
- Slash command for explicit sub-agent dispatch.

## Risks

- **Gemma4 tool-calling reliability.** Open-weights models lag commercial
  ones on tool use. Mitigation: tool names and schemas mirror well-known
  Claude/OpenAI conventions to maximize prior; runaway detection caps damage
  when the model gets confused.
- **4096-token context.** Real coding sessions will hit this fast. Mitigation:
  aggressive context pruning, slash-command `/clear` is one keystroke away,
  document the limit prominently in README.
- **Single point of failure on Ava uptime.** If Ava's vast.ai box is down,
  AvaDex is down. Acceptable for v1 — same risk Ana already lives with.
