"""FastMCP server exposing Claude Code tmux orchestration tools."""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from . import metadata, session

app = FastMCP(
    "claude-code-mcp",
    instructions=(
        "Control interactive Claude Code sessions running inside tmux on behalf of "
        "an orchestrator agent (e.g. Hermes). Use session_send to send a prompt — or "
        "steer a follow-up message into an already-running session — and get only the "
        "final answer (token-efficient). Use session_start to pre-create/resume, "
        "health for a system status overview, session_status for a single session, "
        "session_interrupt to send Ctrl-C mid-run, and session_destroy to clean up."
    ),
)


@app.tool()
def health() -> dict:
    """System health check: binary availability + summary of all known sessions.

    Returns:
    - ``tmux_available`` / ``claude_available`` — whether the required binaries
      are on PATH.
    - ``session_count`` — total number of known sessions.
    - ``sessions`` — list of SessionInfo dicts (same shape as session_status).
    """
    sessions = session.list_sessions()
    return {
        "tmux_available": session._tmux_ok(),
        "claude_available": session._claude_ok(),
        "session_count": len(sessions),
        "sessions": sessions,
    }


@app.tool()
def session_start(
    name: str,
    claude_session_id: str | None = None,
    working_dir: str | None = None,
) -> dict:
    """Create a new tmux + Claude Code session or reconnect to an existing one.

    - If a tmux session called *name* already exists it is returned as-is.
    - If metadata for *name* includes a stored Claude session ID (or one is
      supplied via *claude_session_id*), ``claude --resume`` is used so the
      conversation history is preserved.
    - Otherwise a fresh ``claude`` session is started.
    - *working_dir* sets the working directory for a new session and is stored
      in metadata so future recreations start in the same place.
    """
    info = session.start_session(
        name,
        claude_session_id=claude_session_id,
        working_dir=working_dir,
    )
    return info.to_dict()


@app.tool()
async def session_send(
    name: str,
    prompt: str,
    timeout: int = 120,
    raw: bool = False,
    claude_session_id: str | None = None,
    working_dir: str | None = None,
) -> dict:
    """Send *prompt* to the named session and return Claude's final answer.

    The session is **automatically created** if it does not exist — there is no
    need to call ``session_start`` first.  Pass *claude_session_id* and/or
    *working_dir* to control how a new session is initialised.

    Blocks until Claude Code goes idle (or *timeout* seconds elapse).
    Returns ``{"response": str, "timed_out": bool, "raw": bool}``.

    Set *raw=True* only when you need the full pane dump for debugging —
    default output is the extracted assistant text only (token-efficient).
    """
    return await session.send_prompt(
        name,
        prompt,
        timeout=float(timeout),
        raw=raw,
        claude_session_id=claude_session_id,
        working_dir=working_dir,
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
    ``claude_session_id``, ``working_dir``.
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
