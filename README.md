# claude-tmux-mcp

An MCP server for orchestrating interactive **Claude Code** sessions running
inside **tmux**. Designed for headless agents (e.g. Hermes) that need to drive
Claude Code programmatically — send prompts, receive only the final answer
(token-efficient by default), interrupt, and resume sessions across restarts.

## Features

- **Send & auto-create** — `session_send` creates the session if it doesn't
  exist yet; no separate `session_start` call required.
- **Create / resume sessions** — stable MCP session name as canonical identity;
  optional `--resume <claude-session-id>` for continuity across tmux restarts.
- **Working directory persistence** — supply `working_dir` once; recreated
  sessions automatically resume in the same directory.
- **Hard interrupt** — sends Ctrl-C; no extra text injected.
- **Health / state** — top-level `health` tool reports binary availability and
  all session states at a glance.
- **Token-efficient** — raw pane dump is opt-in via `raw=True`; default output
  is the extracted assistant text only.
- **Pure stdlib + mcp SDK** — no heavy dependencies.

## Why not `claude -p`?

`claude -p` (print / pipeline mode) runs a single prompt non-interactively and
exits immediately after printing the result. Because the process terminates
after one response, there is **no interactive channel** through which tmux can
inject follow-up prompts. You would need to spawn a completely new process for
every turn, losing all conversation context.

This server uses the **interactive REPL** (`claude` with no flags) so that
prompts can be injected via tmux key injection at any time, the conversation
history accumulates inside the running process, and mid-run interrupts (`Ctrl-C`)
work as expected.

## Requirements

| Tool | Version |
|------|---------|
| Python | ≥ 3.11 |
| tmux | ≥ 3.4 |
| Claude Code | ≥ 2.0 |

## Installation

```bash
pip install claude-tmux-mcp
```

Or with [uv](https://docs.astral.sh/uv/):

```bash
uv tool install claude-tmux-mcp
```

For development:

```bash
git clone https://github.com/joschi655/claude-code-tmux-mcp
cd claude-code-tmux-mcp
pip install -e ".[dev]"
```

## MCP configuration

### Claude Desktop / Claude Code (`~/.claude/claude_desktop_config.json`)

```json
{
  "mcpServers": {
    "claude-tmux": {
      "command": "claude-tmux-mcp"
    }
  }
}
```

### With uvx (no install required)

```json
{
  "mcpServers": {
    "claude-tmux": {
      "command": "uvx",
      "args": ["claude-tmux-mcp"]
    }
  }
}
```

### Hermes / custom MCP client

```json
{
  "mcpServers": {
    "claude-tmux": {
      "command": "python",
      "args": ["-m", "claude_tmux_mcp"]
    }
  }
}
```

## Tools

### `health()`

System health check: returns binary availability and a summary of all known
sessions.

```json
{
  "tmux_available": true,
  "claude_available": true,
  "session_count": 1,
  "sessions": [...]
}
```

---

### `session_send(name, prompt, timeout?, raw?, claude_session_id?, working_dir?)`

Send a prompt and get Claude's final answer. **The session is created
automatically if it does not exist** — no separate `session_start` call needed.

```json
{ "name": "hermes-main", "prompt": "List files in /tmp" }
```

Returns:

```json
{ "response": "...", "timed_out": false, "raw": false }
```

- `timeout` (default 120 s) — give up after this many seconds.
- `raw=true` — returns the full pane dump instead of the extracted answer
  (useful for debugging).
- `claude_session_id` — used when auto-creating: runs `claude --resume <id>`.
- `working_dir` — used when auto-creating: starts the session in this directory
  and stores it in metadata for future recreations.

---

### `session_start(name, claude_session_id?, working_dir?)`

Explicitly create a new tmux + Claude Code session, or reconnect to an
existing one.

- If a tmux session called `name` already exists it is returned as-is.
- If metadata for `name` has a stored `claude_session_id`, runs
  `claude --resume <id>` to restore conversation history.
- `working_dir` is stored in metadata so future recreations start in the same
  directory.

```json
{ "name": "hermes-main", "working_dir": "/home/user/myproject" }
```

Returns `SessionInfo` with `tmux_alive`, `claude_alive`, `state`,
`claude_session_id`, `working_dir`.

---

### `session_interrupt(name)`

Send Ctrl-C to abort the current operation. No extra text is sent.

---

### `session_status(name)`

Health check for a single session.

```json
{
  "name": "hermes-main",
  "tmux_alive": true,
  "claude_alive": true,
  "state": "idle",
  "claude_session_id": null,
  "working_dir": "/home/user/myproject"
}
```

---

### `session_list()`

List all managed sessions (from metadata) plus all live tmux sessions.

---

### `session_destroy(name)`

Kill the tmux session and remove stored metadata.

---

### `session_set_claude_id(name, claude_session_id)`

Associate a Claude session ID with `name` so future restarts can use
`--resume`. Call this after the session is running and you know the ID
(e.g. from `/session-id` inside Claude Code).

## Typical workflow

```
# Option A: one-step (session is auto-created)
session_send("hermes-main", "implement feature X and run the tests")
# → creates session if needed, waits for Claude to start, returns final answer

# Option B: explicit lifecycle
session_start("hermes-main", working_dir="/home/user/myproject")
session_send("hermes-main", "implement feature X and run the tests")
# → returns only Claude's final answer

# Interrupt if stuck
session_interrupt("hermes-main")

# System overview
health()
# → { tmux_available: true, claude_available: true, session_count: 1, ... }

# Single session check
session_status("hermes-main")
# → { state: "idle", working_dir: "/home/user/myproject", ... }

# Tear down
session_destroy("hermes-main")
```

## Session ID and `--resume`

Claude Code stores conversation history under a session ID. To preserve
this across tmux restarts:

1. Run `session_send("name", "/session-id")` to ask Claude for its ID.
2. Call `session_set_claude_id("name", "<id>")` to persist it.
3. After a restart, `session_start("name")` (or `session_send`) will
   automatically `--resume`.

## Development

```bash
# Unit tests (no tmux/claude required)
pytest tests/test_parser.py tests/test_session_logic.py -v

# Integration tests (requires tmux + claude)
CLAUDE_TMUX_INTEGRATION=1 pytest tests/test_integration.py -v
```

## License

MIT — see [LICENSE](LICENSE).
