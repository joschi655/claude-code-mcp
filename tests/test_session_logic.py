"""Unit tests for metadata and SessionInfo — no tmux required."""
from __future__ import annotations

import importlib
import json
import os
import tempfile

import pytest

from claude_tmux_mcp.session import SessionInfo


# ---------------------------------------------------------------------------
# metadata module (reload to pick up per-test XDG_DATA_HOME)
# ---------------------------------------------------------------------------

def _meta(tmpdir: str):
    """Return a freshly reloaded metadata module pointing at *tmpdir*."""
    import claude_tmux_mcp.metadata as m
    # Patch the path at module level for this call
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
        os.makedirs(os.path.join(d, "claude-tmux-mcp"), exist_ok=True)
        p = os.path.join(d, "claude-tmux-mcp", "sessions.json")
        with open(p, "w") as f:
            f.write("not json{{{{")
        m = _meta(d)
        assert m.load("anything") is None


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
    assert info.to_dict()["claude_session_id"] is None
