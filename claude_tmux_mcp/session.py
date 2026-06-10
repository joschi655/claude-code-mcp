"""tmux session lifecycle and prompt dispatch for Claude Code sessions."""
from __future__ import annotations

import asyncio
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass
from typing import Any

from . import metadata
from .parser import SessionState, detect_state, extract_response


@dataclass
class SessionInfo:
    name: str
    tmux_alive: bool
    claude_alive: bool
    state: str          # SessionState.value
    claude_session_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Low-level tmux helpers
# ---------------------------------------------------------------------------

def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(args), capture_output=True, text=True)


def _tmux_ok() -> bool:
    return bool(shutil.which("tmux"))


def _claude_ok() -> bool:
    return bool(shutil.which("claude"))


def session_alive(name: str) -> bool:
    return _run("tmux", "has-session", "-t", name).returncode == 0


def get_pane(name: str, *, full_history: bool = False) -> str:
    args = ["tmux", "capture-pane", "-p"]
    if full_history:
        args += ["-S", "-"]
    args += ["-t", f"{name}:0.0"]
    return _run(*args).stdout


def send_keys(name: str, text: str) -> None:
    _run("tmux", "send-keys", "-t", f"{name}:0.0", text, "Enter")


def send_ctrl_c(name: str) -> None:
    _run("tmux", "send-keys", "-t", f"{name}:0.0", "C-c")


# ---------------------------------------------------------------------------
# State polling
# ---------------------------------------------------------------------------

async def _wait_for_idle(name: str, timeout: float) -> bool:
    """Poll until Claude Code goes idle or timeout expires."""
    deadline = time.monotonic() + timeout

    # Give Claude up to 5 s to show "esc to interrupt" after input is sent
    for _ in range(10):
        if detect_state(get_pane(name)) == SessionState.BUSY:
            break
        await asyncio.sleep(0.5)

    # Wait for stable idle (two consecutive checks)
    stable = 0
    while time.monotonic() < deadline:
        if detect_state(get_pane(name)) == SessionState.IDLE:
            stable += 1
            if stable >= 2:
                return True
        else:
            stable = 0
        await asyncio.sleep(0.5)

    return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_status(name: str) -> SessionInfo:
    meta = metadata.load(name) or {}
    tmux_alive = session_alive(name) if _tmux_ok() else False
    claude_alive = False
    state = SessionState.MISSING

    if tmux_alive:
        content = get_pane(name)
        state = detect_state(content)
        claude_alive = bool(content.strip())

    return SessionInfo(
        name=name,
        tmux_alive=tmux_alive,
        claude_alive=claude_alive,
        state=state.value,
        claude_session_id=meta.get("claude_session_id"),
    )


def start_session(
    name: str,
    claude_session_id: str | None = None,
) -> SessionInfo:
    """Create a new session or reconnect to an existing one.

    Priority for determining the Claude command to run:
      1. Explicit *claude_session_id* argument
      2. Stored metadata for *name*
      3. Fresh ``claude`` session (no --resume)
    """
    if not _tmux_ok():
        raise RuntimeError("tmux not found in PATH")
    if not _claude_ok():
        raise RuntimeError("claude not found in PATH")

    if session_alive(name):
        if claude_session_id:
            metadata.save(name, claude_session_id=claude_session_id)
        return get_status(name)

    meta = metadata.load(name) or {}
    resume_id = claude_session_id or meta.get("claude_session_id")

    _run("tmux", "new-session", "-d", "-s", name, "-x", "220", "-y", "50")

    cmd = f"claude --resume {resume_id}" if resume_id else "claude"
    send_keys(name, cmd)

    metadata.save(name, claude_session_id=resume_id)
    return get_status(name)


async def send_prompt(
    name: str,
    prompt: str,
    *,
    timeout: float = 120.0,
    raw: bool = False,
) -> dict[str, Any]:
    """Send *prompt* to the session, wait for idle, return the response.

    Returns ``{"response": str, "timed_out": bool, "raw": bool}``.
    Set *raw=True* to get the unprocessed pane dump instead of the
    extracted assistant answer.
    """
    if not session_alive(name):
        raise ValueError(f"Session '{name}' does not exist; call session_start first")

    if detect_state(get_pane(name)) == SessionState.BUSY:
        raise RuntimeError(f"Session '{name}' is currently busy")

    before = get_pane(name, full_history=True)
    send_keys(name, prompt)

    timed_out = not await _wait_for_idle(name, timeout=timeout)
    after = get_pane(name, full_history=True)

    if raw:
        return {"response": after, "timed_out": timed_out, "raw": True}

    return {
        "response": extract_response(before, after, prompt),
        "timed_out": timed_out,
        "raw": False,
    }


def destroy_session(name: str) -> None:
    if session_alive(name):
        _run("tmux", "kill-session", "-t", name)
    metadata.delete(name)


def list_sessions() -> list[dict[str, Any]]:
    """Return status dicts for all managed + all running tmux sessions."""
    managed = set(metadata.list_names())

    r = _run("tmux", "list-sessions", "-F", "#{session_name}")
    tmux_names: set[str] = set()
    if r.returncode == 0:
        tmux_names = {ln.strip() for ln in r.stdout.splitlines() if ln.strip()}

    return [get_status(n).to_dict() for n in sorted(managed | tmux_names)]
