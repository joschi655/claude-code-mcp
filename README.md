# claude-tmux-mcp

An MCP server for orchestrating interactive **Claude Code** sessions running
inside **tmux**. Designed for headless agents (e.g. Hermes) that need to drive
Claude Code programmatically — send prompts, receive only the final answer
(token-efficient by default), interrupt, and resume sessions across restarts.

## Features

- **Create / resume sessions** — stable MCP session name as canonical identity;
  optional `--resume <claude-session-id>` for continuity across tmux restarts.
- **Send & receive** — send a prompt, block until Claude is idle, return the
  extracted assistant answer only (no TUI chrome or tool-call noise).
- **Hard interrupt** — sends Ctrl-C; no extra text injected.
- **Health / state** — reports `tmux_alive`, `claude_alive`, and
  `state` (idle / busy / missing).
- **Token-efficient** — raw pane dump is opt-in via `raw=True`.
- **Pure stdlib + mcp SDK** — no heavy dependencies.

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

### `session_start(name, claude_session_id?)`

Create a new tmux + Claude Code session, or reconnect to an existing one.

- If a tmux session called `name` already exists it is returned as-is.
- If metadata for `name` has a stored `claude_session_id`, runs
  `claude --resume <id>` to restore conversation history.
- Otherwise starts a fresh `claude` session.

```json
{ "name": "hermes-main" }
```

Returns `SessionInfo` with `tmux_alive`, `claude_alive`, `state`,
`claude_session_id`.

---

### `session_send(name, prompt, timeout?, raw?)`

Send a prompt and get Claude's final answer.

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
  "claude_session_id": null
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
# 1. Create / resume
session_start("hermes-main")

# 2. Work
session_send("hermes-main", "implement feature X and run the tests")
# → returns only Claude's final answer

# 3. Interrupt if stuck
session_interrupt("hermes-main")

# 4. Health check
session_status("hermes-main")
# → { state: "idle", ... }

# 5. Tear down
session_destroy("hermes-main")
```

## Session ID and `--resume`

Claude Code stores conversation history under a session ID. To preserve
this across tmux restarts:

1. Run `session_send("name", "/session-id")` to ask Claude for its ID.
2. Call `session_set_claude_id("name", "<id>")` to persist it.
3. After a restart, `session_start("name")` will automatically `--resume`.

## Development

```bash
# Unit tests (no tmux/claude required)
pytest tests/test_parser.py tests/test_session_logic.py -v

# Integration tests (requires tmux + claude)
CLAUDE_TMUX_INTEGRATION=1 pytest tests/test_integration.py -v
```

## License

MIT — see [LICENSE](LICENSE).
