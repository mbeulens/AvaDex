# AvaDex

Local CLI agent powered by the Syntec Ava assistant.

Stable since 1.0.0: the CLI flags, `config.toml` keys, allowlist format
and tool set are settled, and changes to them follow semantic versioning.
The flags added since (`--allow-tools`, `--output-format`,
`--ignore-user-config`, `--require-private`, `avadex models`) are covered too.

## Install

```bash
pipx install .
```

## First-time setup

```bash
avadex set-key
# Enter your Ava URL (e.g. https://ava.example.com) and an Ava API key.
# Saves both to ~/.config/avadex/config.toml as ava_url / ava_token.
```

Get an API key from an Ava admin: the **API keys** screen in Ava, or
`api_keys.py --add-key <label>` on the Ava server. Ask for a **private** key if
you'll send customer data: Ava then skips RAG and doesn't learn from your
traffic. The server's `AVA_SYNTEC_API_KEY` bootstrap key also works.

If you write `config.toml` by hand, the fields are `ava_url` and `ava_token`
(not `api_key`). See [Configuration](#configuration).

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
(`~/.config/avadex/allowlist.toml`, plus a project-local one — see
[Working directory](#working-directory)).

Pass **`--yes`** (or `-y`) to run the REPL autonomously: every tool call —
writes and shell included — is auto-approved with no per-action prompt. Use it
deliberately; it removes the human checkpoint before destructive actions.

```bash
avadex --yes    # autonomous REPL: no confirmation prompts
```

### Working directory

By default AvaDex works in the directory you launch it from. Point it
somewhere else with `--workdir`:

```bash
avadex --workdir ~/projects/testsite
```

Or set a default in `~/.config/avadex/config.toml`:

```toml
workdir = "/home/you/projects/testsite"
```

`--workdir` wins over the config value, which wins over the current
directory. `~` is expanded, and a relative path is resolved against the
directory you ran the command from. AvaDex `chdir`s into the workdir at
startup, so everything follows it:

| What | Resolved in the workdir |
|------|-------------------------|
| `skills/<name>/SKILL.md` | project skills, merged over global ones |
| `.mcp.json` + `.env` | project MCP servers |
| `.avadex/allowlist.toml` | project permission rules |
| `bash`, `glob`, `grep_files`, relative file paths | the agent's tools |

The `cwd` line in the startup banner shows which directory is in effect.
A workdir that doesn't exist (or isn't a directory) exits with status 2.

#### Project-local allowlist

`<workdir>/.avadex/allowlist.toml` holds permission rules for one project.
Its rules are **added to** your global ones rather than replacing them, so a
project file can only widen what's permitted — your global rules keep working
everywhere.

When a workdir is in play, `/allow` writes new rules to the project file
instead of the global one, creating it on demand. The two files are never
mixed on save, so a project rule can't leak into your global allowlist.
That makes `.avadex/allowlist.toml` safe to commit when a team shares the
same safe commands:

```toml
[[rules]]
tool = "bash"
pattern = "npm test *"
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

For unattended runs (another program driving AvaDex), combine the flags below:

```bash
avadex --config run/avadex.toml --ignore-user-config --workdir run \
       --allow-tools read_file,grep_files,mcp__syntec-forms --require-private \
       --output-format json --model gemma4:26b --prompt "..."
```

#### Restricting tools: `--allow-tools`

Headless mode approves every tool call, so the tool set **is** the security
boundary. `--allow-tools LIST` names exactly which tools a run may use:

| Entry | Grants |
|-------|--------|
| `read_file` | a tool, by exact name |
| `mcp__<server>` | every tool of that MCP server (by its name in `.mcp.json` / config) |
| `mcp__<server>__<tool>` | one MCP tool, by the name the server reports |
| `<server>_<tool>` | the same MCP tool, by the name the model sees |

- Tools outside the list are **not sent to the model** and are **refused at
  dispatch**, so a hallucinated tool name can't get through. Each refusal is
  printed to stderr and listed in the JSON output's `permission_denials`.
- It **fails closed**: an entry that matches no available tool (a typo, or an
  MCP server that failed to start) exits **2** before Ava is called.
- `load_skill` is a tool too. List it if the run should use skills.
- The system prompt tells the model which tools it has.
- Without the flag every tool is available, as before. The flag also works in
  the REPL.

#### Machine-readable output: `--output-format json`

With `--prompt`, prints one JSON object instead of the plain answer (shaped
after Claude Code's result envelope):

```json
{"type": "result", "subtype": "success", "is_error": false,
 "result": "<final answer>", "errors": [],
 "requested_model": "gemma4:26b", "model": "gemma4:26b", "models_used": ["gemma4:26b"],
 "usage": {"input_tokens": 3398, "output_tokens": 91}, "usage_complete": true,
 "num_requests": 3, "duration_ms": 5120, "permission_denials": [],
 "transcript": [
   {"tool": "syntec-forms_form_list", "server": "syntec-forms", "input": {},
    "output": "[{\"id\":\"45\",\"name\":\"Aanhef\"}, ...]",
    "is_error": false, "status": "ok"}],
 "ava": {"key": "my-key", "private": true, "rag": false, "retained": false},
 "ava_changed": false}
```

- `usage` sums every Ava request in the run: tool round-trips, retries and
  context compaction.
- `usage_complete: false` means some response had no real token count
  (older Ava, or a prompt Ollama served from cache). Treat that as unknown,
  not zero.
- **Compare `requested_model` with `model`.** Ava silently falls back to its
  default when the requested model isn't installed. `model` is what ran.
- `ava` is the key-privacy block from Ava's last response (`null` against
  Ava < 0.4.6). `ava_changed` is true when it differed, appeared or
  disappeared between requests in the run.
- `transcript` lists every tool call in order: the `tool`, its MCP `server`
  (`null` for built-ins), the `input`, and the `output` **verbatim and
  untruncated**. Read deciding facts ("does this record exist?") from here,
  not from the model's `result`. `status` is one of:
  - `ok`: the call ran and returned `output`.
  - `error`: the call failed, was refused or was denied. `output` is the
    error text. Don't treat it as evidence.
  - `no_result`: the call started but no result came back. `output` is `null`.
  - `not_run`: the model asked for it, but the run aborted first (`reason`
    says why). `output` is `null`.

  An image result (`attach_image`) is recorded as its media type and size in
  bytes, not the image data. The transcript holds no model reasoning or
  message history.
- A failed run still prints the envelope (`is_error: true`) and exits 1.
  `--output-format json` without `--prompt` exits 2.

#### Private keys only: `--require-private`

Ava can mark an API key **private**: no RAG for its requests, and nothing it
sends is learned into Ava's knowledge base. `--require-private` makes AvaDex
fail closed unless Ava confirms that for the key it's using:

- **Before the prompt is sent**, it checks `GET /api/v1/models`. If the key is
  not reported as private, nothing is sent to `/messages` and the run exits 1.
- **On every response** (including context-compaction calls), if the key stops
  being reported as private, the run aborts at once, before that response's
  tool calls execute or another request goes out.

Only an explicit `"private": true` passes. A missing block (Ava < 0.4.6)
counts as not private. The request whose response reveals a flip has already
reached Ava, so this bounds a mid-run change to one request. It can't make
that request unhappen.

#### Using only the caller's config: `--ignore-user-config`

`--config PATH` replaces `~/.config/avadex/config.toml`, but two things from the
invoking user's home still merge in: the global allowlist and the global
skills. `--ignore-user-config` (requires `--config`) drops both, so a run uses
only the given config file and the workdir.

| Source | Default | With `--ignore-user-config` |
|--------|---------|-----------------------------|
| `config.toml` | `--config` replaces the default (never merged) | same |
| `~/.config/avadex/allowlist.toml` | merged | ignored |
| `~/.config/avadex/skills/` | merged (workdir wins on name clash) | ignored |
| `<workdir>/.mcp.json` | replaces the config's `mcp_servers` | same |
| `<workdir>/.env` | overlays the process env for MCP headers | same |
| `<workdir>/.avadex/allowlist.toml` | merged when present or `--workdir` is set | same |

Logs (`~/.local/state/avadex/`) and REPL history are still written to the home
directory. They're output, not configuration.

### Listing models

```bash
avadex models           # one per line: id, size, (default)
avadex models --json    # {"models": [{"id": ..., "size": ...}], "default": ...}
```

Lists what Ava's `GET /api/v1/models` accepts. Tool support depends on the
model: `ollama show <model>` on the Ava server lists a `tools` capability, and
even then a model can emit tool calls as text (AvaDex reports that as an
error). Test a model with a one-tool `--allow-tools` run before relying on it.

That test only shows that tool calling works, not that the model reads the
results correctly. A run can end with exit 0 and `is_error: false` and still
give a wrong answer. Counting a long tool result, for example, is unreliable
for nearly every model, and the same prompt can give a different number on
the next run. So for data questions:

- Let a tool produce numbers (a total or a count query). The model should
  repeat a number, never count items itself.
- Check existence with a filter ("zero results or not"), not by counting or
  scanning a full listing.
- When a fact decides what happens next, such as whether a record already
  exists before creating one, check the tool result in your own code rather
  than relying on the model's summary.

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

Plus any tools from MCP servers you've configured. The model sees them as
`<server>_<tool>`, with every character outside `[A-Za-z0-9_]` replaced by `_`
(so `syntec-forms` + `get.form` becomes `syntec_forms_get_form`).

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
`~/.config/avadex/allowlist.toml` or a project's
`.avadex/allowlist.toml`, and review the proposed action in
each `[y/n/a]` prompt before pressing `y`.

A project allowlist is read from whatever directory you point AvaDex at, so
treat a checked-in `.avadex/allowlist.toml` as executable content: read it
before running AvaDex in a repository you don't control.

Headless (`--prompt`) and `--yes` runs approve every tool call. When another
program drives AvaDex unattended, restrict the run with `--allow-tools` and use
`--ignore-user-config`, so the tool set is exactly what the caller granted.

## Known limitations

- Ava's `/api/v1/messages` is non-streaming — each turn shows a "..."
  spinner until the response arrives.
- Ava's agent API runs at a 32768-token context (`num_ctx`); AvaDex manages
  long sessions with hybrid context management (dedup + proactive compaction,
  see CHANGELOG 0.3.0).
- No standalone web-search / RAG *tools* — Ava doesn't expose those endpoints.
  Auto-RAG fires server-side on every request (at web-chat parity) unless the
  API key is private, and the system prompt steers the agent to answer domain
  questions from that injected knowledge rather than searching local files.
- Linux only.

## Develop

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

Run with `--debug` to also write verbose logs to `~/.local/state/avadex/debug.log`
(rotating, 1 MB × 5 files). They go to that file, not to stderr. Each Ava
request logs `tools=N`, which is a quick way to check an `--allow-tools` run:

```bash
avadex --debug
```

## License

Private. © 2026 Martijn Beulens (Syntec).
