# Smoke checklist — run before each release

Against a real Ava instance:

1. **Login**
   - `avadex login` with valid creds → "logged in" message.
   - `cat ~/.config/avadex/config.toml` → has `ava_url`, `ava_token`.
   - `avadex login` with bad password → "login failed: HTTP 401", exit 1.

2. **Plain chat**
   - `avadex`, then `Ava> what is 2+2?` → text answer.
   - `Ava> /clear` → "conversation cleared".
   - `Ava> /tools` → lists at least `read_file`, `write_file`, `edit_file`, `bash`.

3. **Coding task**
   - `Ava> read pyproject.toml and tell me the python version requirement`
     → reads the file (one `●` tool call), responds.
   - `Ava> add a comment '# test' to the top of /tmp/x.py`
     → prompts before `write_file`; press `y`; verify `/tmp/x.py`.

4. **System task with permission prompt**
   - `Ava> what's in /etc/hostname?` → `read_file` runs without prompt.
   - `Ava> what disk space is free?` → `bash df -h` prompts; press `a`,
     enter `df *` → next disk-related call doesn't prompt.

5. **Ctrl-C abort**
   - During a long task, press Ctrl-C → "interrupted", returns to prompt
     with history intact.

6. **MCP plug-in (optional)**
   - Add an entry for `mcp-server-filesystem` to config.
   - Start REPL → `/tools` includes namespaced `filesystem.*`.
   - Run a turn that uses one of them.
