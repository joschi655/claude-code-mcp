"""FastMCP server exposing Claude Code tmux orchestration tools."""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from . import metadata, session

app = FastMCP(
    "claude-tmux-mcp",
    instructions=(
        "Orchestrate interactive Claude Code sessions running inside tmux. "
        "Use session_start to create/resume, session_send to prompt and get the "
        "final answer, session_status for health checks, session_interrupt to "
        "send Ctrl-C, and session_destroy to clean up."
    ),
)


@app.tool()
def session_start(
    name: str,
    claude_session_id: str | None = None,
) -> dict:
    """Create a new tmux + Claude Code session or reconnect to an existing one.

    - If a tmux session called *name* already exists it is returned as-is.
    - If metadata for *name* includes a stored Claude session ID (or one is
      supplied via *claude_session_id*), ``claude --resume`` is used so the
      conversation history is preserved.
    - Otherwise a fresh ``claude`` session is started.
    """
    info = session.start_session(name, claude_session_id=claude_session_id)
    return info.to_dict()


@app.tool()
async def session_send(
    name: str,
    prompt: str,
    timeout: int = 120,
    raw: bool = False,
) -> dict:
    """Send *prompt* to the named session and return Claude's final answer.

    Blocks until Claude Code goes idle (or *timeout* seconds elapse).
    Returns ``{"response": str, "timed_out": bool, "raw": bool}``.

    Set *raw=True* only when you need the full pane dump for debugging —
    default output is the extracted assistant text only (token-efficient).
    """
    return await session.send_prompt(
        name, prompt, timeout=float(timeout), raw=raw
    )


@app.tool()
def session_interrupt(name: str) -> dict:
    """Send Ctrl-C to the named session to abort the current operation."""
    if not session.session_alive(name):
        raise ValueError(f"Session '{name}' does not exist")
    session.send_ctrl_c(name)
    return {"interrupted": True, "name": name}


@app.tool()
def session_status(name: str) -> dict:
    """Return health/state info for the named session.

    Fields: ``tmux_alive``, ``claude_alive``, ``state`` (idle/busy/missing),
    ``claude_session_id``.
    """
    return session.get_status(name).to_dict()


@app.tool()
def session_list() -> list:
    """List all managed sessions (metadata) plus any live tmux sessions."""
    return session.list_sessions()


@app.tool()
def session_destroy(name: str) -> dict:
    """Kill the tmux session and remove its stored metadata."""
    session.destroy_session(name)
    return {"destroyed": True, "name": name}


@app.tool()
def session_set_claude_id(name: str, claude_session_id: str) -> dict:
    """Associate a Claude session ID with *name* for future --resume support.

    Call this after you learn the Claude session ID (e.g. via `/session` inside
    Claude Code) so the server can recreate the session with ``--resume`` later.
    """
    metadata.save(name, claude_session_id=claude_session_id)
    return {"name": name, "claude_session_id": claude_session_id}
