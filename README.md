# AvaDex

Local CLI agent powered by Ana's self-hosted Ava assistant.

## Install

```bash
pipx install .
```

## First-time setup

```bash
avadex set-key
# Enter your Ava URL (e.g. https://ava.example.com) and the value of
# AVA_SYNTEC_API_KEY from the Ava server's environment.
# Saves both to ~/.config/avadex/config.toml
```

The API key is the value of `AVA_SYNTEC_API_KEY` on the Ava server. Find it with
`systemctl show ava | grep AVA_SYNTEC_API_KEY` or check the systemd unit /
`.env` file. If unset, the default is `"syntec-ava-local"`.

## Run

```bash
avadex          # opens REPL
```

Type a request like:

```
Ava> add a healthcheck endpoint to server.py
```

The prompt supports multi-line input. Press **Enter** to submit, and
**Esc-Enter** (or **Ctrl-J**, which some terminals send for Shift-Enter)
to insert a newline.

AvaDex will call tools (file reads, edits, shell) and prompt before any
write or shell command unless the action matches your allowlist
(`~/.config/avadex/allowlist.toml`).

Pass **`--yes`** (or `-y`) to run the REPL autonomously: every tool call —
writes and shell included — is auto-approved with no per-action prompt. Use it
deliberately; it removes the human checkpoint before destructive actions.

```bash
avadex --yes    # autonomous REPL: no confirmation prompts
```

### Headless / scripted use

```bash
avadex --prompt "Translate 'cage' from English to Dutch"
# → kooi

avadex --model qwen3.6:27b --prompt "List Syntec partners in Belgium as a table"
echo $?    # 0 on success, non-zero on error
```

With `--prompt TEXT`, AvaDex runs a single agent turn (no REPL), writes only
the final assistant answer to stdout (errors to stderr), and exits. The agent's
internal tool-use loop iterates as normal — MCP servers, file tools, bash —
capped by `max_iterations` (default 50, configurable). Tool prompts
**auto-approve** in headless mode since there's no human to ask (the same
auto-approval `--yes` enables for the REPL). `--model NAME` overrides the model
in both headless and REPL mode.

## Tools

Built-in (always available):

| Tool          | Purpose                                                          |
|---------------|------------------------------------------------------------------|
| `read_file`   | Read a UTF-8 text file (1 MB cap).                               |
| `write_file`  | Create or overwrite a file. Creates parent dirs.                 |
| `edit_file`   | Replace one exact occurrence of `old_string` with `new_string`.  |
| `multi_edit`  | Apply several edits to one file atomically.                      |
| `glob`        | Find files matching a glob pattern (`**` for recursion).         |
| `grep_files`  | Search file contents with a Python regex.                        |
| `bash`        | Run a shell command. Default 30s timeout, max 600s.              |
| `bash_bg`     | Start a long-running shell job; returns a `job_id`.              |
| `bash_output` | Read accumulated output + status of a background job.            |
| `kill_bash`   | Terminate a background job (SIGTERM → SIGKILL after 5s).         |
| `bash_list`   | List all background jobs.                                        |
| `web_fetch`   | GET a URL, return body (up to 100 KB, follows redirects).        |
| `attach_image`| Attach a local image (jpg/png/gif/webp/bmp, ≤5 MB) for a vision model to read. |
| `todo_write`  | Replace the session todo list (for multi-step planning).         |
| `todo_read`   | Read the current todo list.                                      |

Plus any tools from MCP servers you've configured (namespaced as `<server>.<tool>`).

## Slash commands

- `/exit` — quit
- `/clear` — reset conversation
- `/tools` — list available tools
- `/model` (or `/model list`) — show a numbered list; then just type the number (e.g. `2`) to pick
- `/model <N>` — one-shot pick by number, no list shown (e.g. `/model 2`)
- `/model <name>` — switch by exact model id
- `/model refresh` — re-fetch the model list
- `/allow <tool> <pattern>` — append a permission rule

## Configuration

`~/.config/avadex/config.toml`:

```toml
ava_url = "https://ava.example.com"
ava_token = "..."
default_model = "gemma4"
max_context_tokens = 3500

[[mcp_servers]]
name = "filesystem"
command = "npx"
args = ["-y", "@modelcontextprotocol/server-filesystem", "/home/you"]
```

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

### Skills

Skills are focused markdown playbooks AvaDex can load on demand. At startup it
discovers them from two places:

- **Global:** `~/.config/avadex/skills/<name>/SKILL.md`
- **Workdir:** `<cwd>/skills/<name>/SKILL.md` (a workdir skill overrides a
  global one with the same name)

Each `SKILL.md` has simple frontmatter plus a markdown body:

```
---
name: create-partner
description: Use when the user asks to create or onboard a partner in Syntec.
---

<the full playbook the agent should follow>
```

AvaDex lists each skill's `name` and `description` in the system prompt and
exposes a `load_skill` tool. When a request matches a skill, the agent calls
`load_skill` to read the full body before acting (the tool is read-only and
runs without a permission prompt). Skills are independent of MCP servers —
pair a skill with a `.mcp.json` in the same directory when it needs specific
tools.

## Security

**AvaDex runs all tools — including `bash`, `bash_bg`, `write_file`,
and `edit_file` — with your user's full privileges. There is no
sandbox.** The allowlist prompts before each risky action, but once
you accept a pattern (or pick `[a]lways`), matching commands run
unrestricted: they can read, modify, or delete any file your user can
touch, talk to any network endpoint your machine can reach, and start
long-running processes.

Treat this like an interactive shell: don't paste prompts from
untrusted sources, be deliberate about what you add to
`~/.config/avadex/allowlist.toml`, and review the proposed action in
each `[y/n/a]` prompt before pressing `y`.

## Known limitations (v1)

- Ava's `/api/v1/messages` is non-streaming — each turn shows a "..."
  spinner until the response arrives.
- Ava's agent API runs at a 32768-token context (`num_ctx`); AvaDex manages
  long sessions with hybrid context management (dedup + proactive compaction,
  see CHANGELOG 0.3.0).
- No standalone web-search / RAG *tools* — Ava doesn't expose those endpoints.
  Auto-RAG fires server-side on every request (at web-chat parity), and the
  system prompt steers the agent to answer domain questions from that injected
  knowledge rather than searching local files.
- Linux only.

## Develop

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

Run with `--debug` to also write verbose logs to `~/.local/state/avadex/debug.log`
(rotating, 1 MB × 5 files):

```bash
avadex --debug
```

## License

Private. © 2026 Martijn Beulens (Syntec).
