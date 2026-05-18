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

The prompt supports multi-line input. Press Enter to add a newline, or
end a line with `;` and press Enter to submit. Esc-Enter also submits.

AvaDex will call tools (file reads, edits, shell) and prompt before any
write or shell command unless the action matches your allowlist
(`~/.config/avadex/allowlist.toml`).

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
- Hard 4096-token context window on Ava's side; AvaDex prunes aggressively.
- No web search / RAG tools yet — Ava doesn't expose standalone endpoints.
  (Auto-RAG fires server-side on every request anyway.)
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
