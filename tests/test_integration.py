"""Integration test scaffold.

Skipped unless CLAUDE_TMUX_INTEGRATION=1 is set in the environment.
Requires a working tmux and claude installation.

Run manually:
    CLAUDE_TMUX_INTEGRATION=1 pytest tests/test_integration.py -v
"""
from __future__ import annotations

import asyncio
import os
import shutil
import time

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("CLAUDE_TMUX_INTEGRATION") != "1",
    reason="Set CLAUDE_TMUX_INTEGRATION=1 to run integration tests",
)

SESSION = f"inttest-{os.getpid()}"


@pytest.fixture(autouse=True)
def cleanup():
    """Ensure the test session is killed after each test."""
    yield
    from claude_code_mcp import session
    if session.session_alive(SESSION):
        session.destroy_session(SESSION)


def _require_tools():
    if not shutil.which("tmux"):
        pytest.skip("tmux not available")
    if not shutil.which("claude"):
        pytest.skip("claude not available")


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

def test_start_and_status():
    _require_tools()
    from claude_code_mcp import session

    info = session.start_session(SESSION)
    assert info.tmux_alive, "tmux session should be alive after start"

    status = session.get_status(SESSION)
    assert status.tmux_alive
    assert status.state in ("idle", "busy", "missing")


def test_start_idempotent():
    _require_tools()
    from claude_code_mcp import session

    i1 = session.start_session(SESSION)
    i2 = session.start_session(SESSION)  # should not raise or create duplicate
    assert i1.name == i2.name


def test_destroy():
    _require_tools()
    from claude_code_mcp import session

    session.start_session(SESSION)
    session.destroy_session(SESSION)
    assert not session.session_alive(SESSION)


def test_list_includes_managed():
    _require_tools()
    from claude_code_mcp import session

    session.start_session(SESSION)
    names = [s["name"] for s in session.list_sessions()]
    assert SESSION in names


# ---------------------------------------------------------------------------
# Interrupt
# ---------------------------------------------------------------------------

def test_interrupt_sends_ctrl_c():
    _require_tools()
    from claude_code_mcp import session

    session.start_session(SESSION)
    # Just check it doesn't raise
    session.send_ctrl_c(SESSION)


# ---------------------------------------------------------------------------
# Prompt / response (requires Claude to actually start and respond)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_and_receive():
    _require_tools()
    from claude_code_mcp import session

    session.start_session(SESSION)
    # Give Claude Code time to start up
    await asyncio.sleep(8)

    result = await session.send_prompt(
        SESSION,
        "Reply with the single word: pong",
        timeout=90,
    )
    assert not result["timed_out"], "Claude did not respond within timeout"
    response = result["response"].lower()
    assert "pong" in response, f"Expected 'pong' in response, got: {result['response']!r}"


@pytest.mark.asyncio
async def test_raw_response_contains_pane_content():
    _require_tools()
    from claude_code_mcp import session

    session.start_session(SESSION)
    await asyncio.sleep(8)

    result = await session.send_prompt(
        SESSION,
        "Reply with the single word: ping",
        timeout=90,
        raw=True,
    )
    assert result["raw"] is True
    assert isinstance(result["response"], str)
    assert len(result["response"]) > 0
