"""tmux session lifecycle and prompt dispatch for Claude Code sessions."""
from __future__ import annotations

import asyncio
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass
from typing import Any

from . import metadata
from .parser import SessionState, detect_state, extract_response, is_startup_screen


@dataclass
class SessionInfo:
    name: str
    tmux_alive: bool
    claude_alive: bool
    state: str          # SessionState.value
    claude_session_id: str | None = None
    working_dir: str | None = None

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
    # -l sends text literally so tmux never interprets key sequences inside *text*.
    # Enter is sent as a separate non-literal keystroke so it is treated as Return.
    _run("tmux", "send-keys", "-l", "-t", f"{name}:0.0", text)
    _run("tmux", "send-keys", "-t", f"{name}:0.0", "Enter")


def send_ctrl_c(name: str) -> None:
    _run("tmux", "send-keys", "-t", f"{name}:0.0", "C-c")


# ---------------------------------------------------------------------------
# State polling
# ---------------------------------------------------------------------------

async def _wait_for_idle(name: str, timeout: float, *, dismiss_startup: bool = False) -> bool:
    """Poll until Claude Code goes idle or timeout expires.

    When *dismiss_startup* is True, automatically press Enter to accept the
    default effort option if the startup selector UI is detected, then continue
    waiting for real idle.
    """
    deadline = time.monotonic() + timeout
    startup_dismissed = False

    # Give Claude up to 5 s to show "esc to interrupt" after input is sent.
    # Break early if the startup screen is already visible.
    for _ in range(10):
        pane = get_pane(name)
        if dismiss_startup and is_startup_screen(pane):
            break
        if detect_state(pane) == SessionState.BUSY:
            break
        await asyncio.sleep(0.5)

    # Wait for stable idle (two consecutive checks).
    # When dismiss_startup is active, the startup screen does not count as idle.
    stable = 0
    while time.monotonic() < deadline:
        pane = get_pane(name)
        if dismiss_startup and is_startup_screen(pane):
            if not startup_dismissed:
                _run("tmux", "send-keys", "-t", f"{name}:0.0", "Enter")
                startup_dismissed = True
            stable = 0
        elif detect_state(pane) == SessionState.IDLE:
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
        working_dir=meta.get("working_dir"),
    )


def start_session(
    name: str,
    claude_session_id: str | None = None,
    working_dir: str | None = None,
) -> SessionInfo:
    """Create a new session or reconnect to an existing one.

    Priority for determining the Claude command to run:
      1. Explicit *claude_session_id* argument
      2. Stored metadata for *name*
      3. Fresh ``claude`` session (no --resume)

    If *working_dir* is given and the session does not yet exist, the tmux
    window is started in that directory and the path is stored in metadata so
    a recreated session resumes in the same place.
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
    wd = working_dir or meta.get("working_dir")

    new_session_cmd = ["tmux", "new-session", "-d", "-s", name, "-x", "220", "-y", "50"]
    if wd:
        new_session_cmd += ["-c", wd]
    _run(*new_session_cmd)

    cmd = f"claude --resume {resume_id}" if resume_id else "claude"
    send_keys(name, cmd)

    fields: dict[str, Any] = {"claude_session_id": resume_id}
    if wd:
        fields["working_dir"] = wd
    metadata.save(name, **fields)
    return get_status(name)


async def send_prompt(
    name: str,
    prompt: str,
    *,
    timeout: float = 120.0,
    raw: bool = False,
    claude_session_id: str | None = None,
    working_dir: str | None = None,
) -> dict[str, Any]:
    """Send *prompt* to the session, wait for idle, return the response.

    If the session does not exist it is automatically created (using
    *claude_session_id* and *working_dir* when provided).

    Returns ``{"response": str, "timed_out": bool, "raw": bool}``.
    Set *raw=True* to get the unprocessed pane dump instead of the
    extracted assistant answer.
    """
    if not session_alive(name):
        start_session(name, claude_session_id=claude_session_id, working_dir=working_dir)
        # Wait for Claude to start up; auto-dismiss the effort-selection screen if shown.
        started = await _wait_for_idle(name, timeout=30.0, dismiss_startup=True)
        if not started:
            raise RuntimeError(
                f"Session '{name}' was auto-created but did not become idle within 30 s"
            )

    pane = get_pane(name)
    if detect_state(pane) == SessionState.BUSY:
        raise RuntimeError(f"Session '{name}' is currently busy")

    # Safety net: dismiss the startup screen even when the session already existed.
    if is_startup_screen(pane):
        _run("tmux", "send-keys", "-t", f"{name}:0.0", "Enter")
        if not await _wait_for_idle(name, timeout=30.0):
            raise RuntimeError(
                f"Session '{name}' did not exit startup screen within 30 s"
            )

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
