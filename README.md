# claude-code-mcp

It ssounds dumb...
but its literally that. Using Claude Code through an MCP server.
Its neant for orchestrator agents (like [**Hermes**](https://github.com/nousresearch/hermes-agent)), giving it fine-grained control over interactive **Claude Code** sessions running inside **tmux**.

The core value: a long-running Claude Code REPL stays alive in a tmux pane, and
your orchestrator can **steer it at any point** — send the initial prompt,
inject a follow-up message mid-session, interrupt a stuck run, or read back
only the final answer (token-efficient by default). Way better than using it through 'claude -p'. 

## Why an orchestrator needs this

When Hermes (or any multi-agent system) delegates a coding task to Claude Code,
it needs more than a one-shot call. It needs to:

| Need | This server's tool |
|------|-------------------|
| Send a prompt, get back only the final answer | `session_send` |
| Steer a follow-up into an already-running session | `session_send` on an existing session |
| Interrupt a runaway or wrong-direction task | `session_interrupt` |
| Check whether Claude is still thinking or idle | `session_status` / `health` |
| Resume a session after a restart without losing history | `session_start` + `--resume` |
| Destroy a session when the task is done | `session_destroy` |

## Why not `claude -p`?

`claude -p` (print / pipeline mode) exits after one response. There is **no
channel to inject a follow-up** — every turn requires spawning a fresh process
and loses accumulated context.

This server keeps the **interactive REPL** (`claude` with no flags) alive in a
tmux pane so prompts can be injected at any time via tmux key injection, history
accumulates inside the running process, and mid-run interrupts (`Ctrl-C`) work
as expected.

## Features

- **Steer mid-session** — `session_send` injects into an already-running
  session as naturally as typing; no restart required.
- **Send & auto-create** — if the session doesn't exist yet it is created
  transparently; no separate `session_start` call required.
- **Resume across restarts** — store a Claude session ID once; all future
  recreations use `claude --resume <id>` automatically.
- **Working directory persistence** — supply `working_dir` once; recreated
  sessions start in the same directory.
- **Hard interrupt** — sends Ctrl-C with no extra text injected.
- **Health / state** — `health` reports binary availability and all session
  states at a glance; `session_status` drills into one session.
- **Token-efficient** — default output is the extracted assistant text only;
  full pane dump is opt-in via `raw=True`.
- **Pure stdlib + mcp SDK** — no heavy dependencies.

## Requirements

| Tool | Version |
|------|---------|
| Python | ≥ 3.11 |
| tmux | ≥ 3.4 |
| Claude Code | ≥ 2.0 |

## Installation

```bash
pip install claude-code-mcp
```

Or with [uv](https://docs.astral.sh/uv/):

```bash
uv tool install claude-code-mcp
```

For development:

```bash
git clone https://github.com/joschi655/claude-code-mcp
cd claude-code-mcp
pip install -e ".[dev]"
```

## MCP configuration

### Claude Desktop / Claude Code (`~/.claude/claude_desktop_config.json`)

```json
{
  "mcpServers": {
    "claude-code-mcp": {
      "command": "claude-code-mcp"
    }
  }
}
```

### With uvx (no install required)

```json
{
  "mcpServers": {
    "claude-code-mcp": {
      "command": "uvx",
      "args": ["claude-code-mcp"]
    }
  }
}
```

### Hermes / custom MCP client

```json
{
  "mcpServers": {
    "claude-code-mcp": {
      "command": "python",
      "args": ["-m", "claude_code_mcp"]
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

Send a prompt to a session — or steer a follow-up into an already-running one —
and return Claude's final answer. **The session is created automatically if it
does not exist.**

```json
{ "name": "hermes-main", "prompt": "Now run the tests and fix any failures" }
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

**Steering example** — Hermes delegates a task, then decides mid-flight to
redirect it:

```python
session_send("hermes-main", "implement feature X")
# … later, while Claude is still idle or about to start a wrong approach …
session_send("hermes-main", "actually focus on the auth module first")
```

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

Send Ctrl-C to abort the current operation. No extra text is sent. Use this
when Hermes detects that Claude is going in the wrong direction and wants to
redirect without waiting for a full response.

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

## Typical orchestrator workflow

```python
# One-step delegation (session is auto-created)
session_send("hermes-main", "implement feature X and run the tests")
# → creates session if needed, waits for Claude to finish, returns final answer

# Steer a follow-up into the running session
session_send("hermes-main", "the tests are failing — fix the import error first")

# Interrupt if Claude is going the wrong way
session_interrupt("hermes-main")
session_send("hermes-main", "forget the previous approach, use the adapter pattern")

# System overview
health()
# → { tmux_available: true, claude_available: true, session_count: 1, ... }

# Single session check
session_status("hermes-main")
# → { state: "idle", working_dir: "/home/user/myproject", ... }

# Tear down when done
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
