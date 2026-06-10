"""Persist session name → Claude session ID mappings on disk."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def _store() -> Path:
    base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    d = base / "claude-code-mcp"
    d.mkdir(parents=True, exist_ok=True)
    return d / "sessions.json"


def _read() -> dict[str, Any]:
    f = _store()
    if f.exists():
        try:
            return json.loads(f.read_text())
        except Exception:
            return {}
    return {}


def _write(data: dict[str, Any]) -> None:
    _store().write_text(json.dumps(data, indent=2))


def save(name: str, **fields: Any) -> None:
    data = _read()
    data.setdefault(name, {}).update(fields)
    _write(data)


def load(name: str) -> dict[str, Any] | None:
    return _read().get(name)


def delete(name: str) -> None:
    data = _read()
    data.pop(name, None)
    _write(data)


def list_names() -> list[str]:
    return list(_read().keys())
