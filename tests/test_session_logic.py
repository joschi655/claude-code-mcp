"""Unit tests for metadata and SessionInfo — no tmux required."""
from __future__ import annotations

import asyncio
import importlib
import json
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from claude_code_mcp.session import SessionInfo
from claude_code_mcp.parser import SessionState


# ---------------------------------------------------------------------------
# metadata module (reload to pick up per-test XDG_DATA_HOME)
# ---------------------------------------------------------------------------

def _meta(tmpdir: str):
    """Return a freshly reloaded metadata module pointing at *tmpdir*."""
    import claude_code_mcp.metadata as m
    os.environ["XDG_DATA_HOME"] = tmpdir
    importlib.reload(m)
    return m


def test_metadata_save_and_load():
    with tempfile.TemporaryDirectory() as d:
        m = _meta(d)
        m.save("s1", claude_session_id="abc123")
        loaded = m.load("s1")
        assert loaded is not None
        assert loaded["claude_session_id"] == "abc123"


def test_metadata_save_updates_existing():
    with tempfile.TemporaryDirectory() as d:
        m = _meta(d)
        m.save("s1", claude_session_id="first")
        m.save("s1", claude_session_id="second")
        assert m.load("s1")["claude_session_id"] == "second"


def test_metadata_delete():
    with tempfile.TemporaryDirectory() as d:
        m = _meta(d)
        m.save("s1", claude_session_id="x")
        m.delete("s1")
        assert m.load("s1") is None


def test_metadata_list_names():
    with tempfile.TemporaryDirectory() as d:
        m = _meta(d)
        m.save("alpha", claude_session_id="1")
        m.save("beta", claude_session_id="2")
        names = m.list_names()
        assert "alpha" in names
        assert "beta" in names


def test_metadata_load_missing_returns_none():
    with tempfile.TemporaryDirectory() as d:
        m = _meta(d)
        assert m.load("nonexistent") is None


def test_metadata_handles_corrupt_file():
    with tempfile.TemporaryDirectory() as d:
        os.makedirs(os.path.join(d, "claude-code-mcp"), exist_ok=True)
        p = os.path.join(d, "claude-code-mcp", "sessions.json")
        with open(p, "w") as f:
            f.write("not json{{{{")
        m = _meta(d)
        assert m.load("anything") is None


def test_metadata_saves_working_dir():
    with tempfile.TemporaryDirectory() as d:
        m = _meta(d)
        m.save("s1", claude_session_id="abc", working_dir="/tmp/myproject")
        loaded = m.load("s1")
        assert loaded["working_dir"] == "/tmp/myproject"
        assert loaded["claude_session_id"] == "abc"


def test_metadata_working_dir_persists_across_saves():
    with tempfile.TemporaryDirectory() as d:
        m = _meta(d)
        m.save("s1", working_dir="/tmp/myproject")
        m.save("s1", claude_session_id="new-id")
        loaded = m.load("s1")
        assert loaded["working_dir"] == "/tmp/myproject"
        assert loaded["claude_session_id"] == "new-id"


# ---------------------------------------------------------------------------
# SessionInfo
# ---------------------------------------------------------------------------

def test_session_info_to_dict():
    info = SessionInfo(
        name="my-agent",
        tmux_alive=True,
        claude_alive=True,
        state="idle",
        claude_session_id="sid-42",
    )
    d = info.to_dict()
    assert d["name"] == "my-agent"
    assert d["state"] == "idle"
    assert d["claude_session_id"] == "sid-42"
    assert d["tmux_alive"] is True


def test_session_info_defaults():
    info = SessionInfo(
        name="bare",
        tmux_alive=False,
        claude_alive=False,
        state="missing",
    )
    assert info.claude_session_id is None
    assert info.working_dir is None
    assert info.to_dict()["claude_session_id"] is None
    assert info.to_dict()["working_dir"] is None


def test_session_info_working_dir():
    info = SessionInfo(
        name="proj",
        tmux_alive=True,
        claude_alive=True,
        state="idle",
        working_dir="/home/user/project",
    )
    d = info.to_dict()
    assert d["working_dir"] == "/home/user/project"


# ---------------------------------------------------------------------------
# send_prompt auto-create behaviour (mocked)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_prompt_autocreates_missing_session():
    """send_prompt should call start_session when the session does not exist."""
    import claude_code_mcp.session as sess

    pane_content = "idle content\n>"

    async def _idle_ok(_name, timeout, **kwargs):
        return True

    with (
        patch.object(sess, "session_alive", return_value=False),
        patch.object(sess, "start_session") as mock_start,
        patch.object(sess, "get_pane", return_value=pane_content),
        patch.object(sess, "detect_state", return_value=SessionState.IDLE),
        patch.object(sess, "is_startup_screen", return_value=False),
        patch.object(sess, "_wait_for_idle", side_effect=_idle_ok),
        patch.object(sess, "send_keys"),
        patch.object(sess, "extract_response", return_value="auto-created response"),
    ):
        result = await sess.send_prompt(
            "new-session",
            "hello",
            claude_session_id="cid-1",
            working_dir="/tmp/proj",
        )

    mock_start.assert_called_once_with(
        "new-session",
        claude_session_id="cid-1",
        working_dir="/tmp/proj",
    )
    assert result["response"] == "auto-created response"
    assert not result["timed_out"]


@pytest.mark.asyncio
async def test_send_prompt_uses_existing_session():
    """send_prompt should NOT call start_session when the session already exists."""
    import claude_code_mcp.session as sess

    pane_content = "idle content\n>"

    async def _idle_ok(_name, timeout, **kwargs):
        return True

    with (
        patch.object(sess, "session_alive", return_value=True),
        patch.object(sess, "start_session") as mock_start,
        patch.object(sess, "get_pane", return_value=pane_content),
        patch.object(sess, "detect_state", return_value=SessionState.IDLE),
        patch.object(sess, "is_startup_screen", return_value=False),
        patch.object(sess, "_wait_for_idle", side_effect=_idle_ok),
        patch.object(sess, "send_keys"),
        patch.object(sess, "extract_response", return_value="existing response"),
    ):
        result = await sess.send_prompt("existing-session", "hello")

    mock_start.assert_not_called()
    assert result["response"] == "existing response"


@pytest.mark.asyncio
async def test_send_prompt_autocreate_uses_dismiss_startup():
    """send_prompt should pass dismiss_startup=True to _wait_for_idle when auto-creating."""
    import claude_code_mcp.session as sess

    pane_content = "idle content\n>"

    async def _idle_ok(_name, timeout, **kwargs):
        return True

    with (
        patch.object(sess, "session_alive", return_value=False),
        patch.object(sess, "start_session"),
        patch.object(sess, "get_pane", return_value=pane_content),
        patch.object(sess, "detect_state", return_value=SessionState.IDLE),
        patch.object(sess, "is_startup_screen", return_value=False),
        patch.object(sess, "_wait_for_idle", side_effect=_idle_ok) as mock_wait,
        patch.object(sess, "send_keys"),
        patch.object(sess, "extract_response", return_value="response"),
    ):
        await sess.send_prompt("new-session", "hello")

    # The bootstrap _wait_for_idle call must carry dismiss_startup=True
    bootstrap_call = mock_wait.call_args_list[0]
    assert bootstrap_call.kwargs.get("dismiss_startup") is True


@pytest.mark.asyncio
async def test_send_prompt_dismisses_startup_on_existing_session():
    """send_prompt should send Enter to dismiss the startup screen on an already-alive session."""
    import claude_code_mcp.session as sess

    startup_pane = "❯ 1. ◐ Medium (recommended)\nEffort determines how long..."
    idle_pane = "idle content\n>"

    async def _idle_ok(_name, timeout, **kwargs):
        return True

    # First get_pane call returns startup screen; subsequent calls return idle
    pane_results = iter([startup_pane, idle_pane, idle_pane])

    with (
        patch.object(sess, "session_alive", return_value=True),
        patch.object(sess, "get_pane", side_effect=lambda n, **kw: next(pane_results, idle_pane)),
        patch.object(sess, "detect_state", return_value=SessionState.IDLE),
        patch.object(sess, "is_startup_screen", side_effect=lambda p: p == startup_pane),
        patch.object(sess, "_wait_for_idle", side_effect=_idle_ok),
        patch.object(sess, "send_keys"),
        patch.object(sess, "_run") as mock_run,
        patch.object(sess, "extract_response", return_value="TEST_OK"),
    ):
        result = await sess.send_prompt("existing-session", "hello")

    # Verify that Enter was sent to dismiss the startup screen
    enter_calls = [c for c in mock_run.call_args_list if "Enter" in str(c)]
    assert len(enter_calls) >= 1
    assert result["response"] == "TEST_OK"


# ---------------------------------------------------------------------------
# health tool
# ---------------------------------------------------------------------------

def test_health_tool_returns_binary_status():
    from claude_code_mcp import server
    import claude_code_mcp.session as sess

    with (
        patch.object(sess, "_tmux_ok", return_value=True),
        patch.object(sess, "_claude_ok", return_value=False),
        patch.object(sess, "list_sessions", return_value=[]),
    ):
        result = server.health()

    assert result["tmux_available"] is True
    assert result["claude_available"] is False
    assert result["session_count"] == 0
    assert result["sessions"] == []


def test_health_tool_reports_sessions():
    from claude_code_mcp import server
    import claude_code_mcp.session as sess

    fake_sessions = [
        {"name": "s1", "state": "idle", "tmux_alive": True, "claude_alive": True,
         "claude_session_id": None, "working_dir": None},
    ]

    with (
        patch.object(sess, "_tmux_ok", return_value=True),
        patch.object(sess, "_claude_ok", return_value=True),
        patch.object(sess, "list_sessions", return_value=fake_sessions),
    ):
        result = server.health()

    assert result["session_count"] == 1
    assert result["sessions"][0]["name"] == "s1"
