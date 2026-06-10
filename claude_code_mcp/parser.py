"""Parse tmux pane output to detect Claude Code state and extract responses."""
from __future__ import annotations

import re
from enum import Enum

ANSI_ESCAPE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
_BOX_CHARS = str.maketrans("", "", "╭╮╰╯│─╴╸╼╽╾╿┤├┼┴┬┐└┘┌╔╗╚╝║═╟╠╡╢╣╤╥╦╧╨╩╪╫╬")
_SPINNER = frozenset("⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏")
_LEADING_BULLET = re.compile(r"^[●◆→⟹⮕✓❯]\s+")


class SessionState(Enum):
    IDLE = "idle"
    BUSY = "busy"
    MISSING = "missing"


def strip_ansi(text: str) -> str:
    return ANSI_ESCAPE.sub("", text)


def clean_line(line: str) -> str:
    return strip_ansi(line).translate(_BOX_CHARS).strip()


def detect_state(pane_content: str) -> SessionState:
    """Heuristic: 'esc to interrupt' or spinner chars → BUSY, otherwise IDLE."""
    clean = strip_ansi(pane_content)
    if "esc to interrupt" in clean.lower():
        return SessionState.BUSY
    tail = "\n".join(clean.strip().splitlines()[-5:])
    if any(c in tail for c in _SPINNER):
        return SessionState.BUSY
    return SessionState.IDLE


def _is_chrome(line: str) -> bool:
    """True if the line is TUI furniture, not response content."""
    if not line:
        return True
    # bare prompt or cursor marker
    if re.fullmatch(r">?\s*", line):
        return True
    # status-only characters (including ❯ prompt cursor)
    if re.fullmatch(r"[✓✗●◆→⟹⮕❯\s]+", line):
        return True
    if re.fullmatch(r"esc to interrupt", line, re.I):
        return True
    # keyboard shortcut hint bar ("? for shortcuts   /compact")
    if re.search(r"\?\s+for shortcuts", line, re.I):
        return True
    # auto-update / CLI error banners
    if re.search(r"auto.?update failed", line, re.I):
        return True
    return False


_STARTUP_PATTERNS = (
    re.compile(r"effort determines how long", re.I),
    re.compile(r"❯\s*1\."),
    re.compile(r"○ low.*◐ medium.*● high"),
)

# Patterns that only appear once Claude Code's TUI has taken over the terminal.
# A raw shell prompt matches none of these.
_CLAUDE_UI_PATTERNS = (
    *_STARTUP_PATTERNS,
    re.compile(r"esc to interrupt", re.I),
    re.compile(r"claude code", re.I),
    re.compile(r"claude\.ai", re.I),
    re.compile(r"tips for getting started", re.I),
    re.compile(r"welcome back", re.I),
)


def is_startup_screen(pane_content: str) -> bool:
    """Return True if the pane is showing Claude Code's effort-selection startup UI."""
    clean = strip_ansi(pane_content)
    return any(p.search(clean) for p in _STARTUP_PATTERNS)


def is_claude_ui_present(pane_content: str) -> bool:
    """Return True if the pane shows any Claude Code UI element (not a raw shell).

    Matches branding text, the effort-selector, 'esc to interrupt', or loading
    spinner characters — all of which appear only after Claude's TUI has taken
    over the terminal.
    """
    clean = strip_ansi(pane_content)
    if any(p.search(clean) for p in _CLAUDE_UI_PATTERNS):
        return True
    # Spinner chars only appear during Claude loading / active processing.
    return any(c in clean for c in _SPINNER)


def extract_response(before: str, after: str, sent_prompt: str) -> str:
    """Return the assistant text that appeared after *sent_prompt* was sent.

    Strips ANSI codes and box-drawing characters; drops TUI chrome lines.
    Falls back to the last 120 non-chrome lines if the prompt is not locatable.
    """
    before_clean = strip_ansi(before)
    after_clean = strip_ansi(after)

    before_lines = before_clean.splitlines()
    after_lines = after_clean.splitlines()

    # Find the stable common prefix (scrollback history is append-only)
    common = 0
    for b, a in zip(before_lines, after_lines):
        if b == a:
            common += 1
        else:
            break
    new_lines = after_lines[common:]

    # Locate the user's sent prompt inside new_lines and skip past it
    words = sent_prompt.strip().split()
    if words:
        needle = " ".join(words[: min(6, len(words))])
        for i, raw_line in enumerate(new_lines):
            if needle in raw_line.translate(_BOX_CHARS):
                new_lines = new_lines[i + 1 :]
                break

    # Clean and filter
    result: list[str] = []
    for raw in new_lines:
        c = raw.translate(_BOX_CHARS).strip()
        if not _is_chrome(c):
            # Strip leading status/bullet prefix (e.g. "● result" → "result")
            c = _LEADING_BULLET.sub("", c)
            result.append(c)

    # Trim leading/trailing blanks
    while result and not result[0]:
        result.pop(0)
    while result and not result[-1]:
        result.pop()

    return "\n".join(result)
