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

AvaDex will call tools (file reads, edits, shell) and prompt before any
write or shell command unless the action matches your allowlist
(`~/.config/avadex/allowlist.toml`).

## Slash commands

- `/exit` — quit
- `/clear` — reset conversation
- `/tools` — list available tools
- `/model` (or `/model list`) — show a numbered list of available models from Ava
- `/model <N>` — switch by 1-based number from the list (e.g. `/model 2`)
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

## License

Private. © 2026 Martijn Beulens (Syntec).
