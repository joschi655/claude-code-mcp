"""Parse tmux pane output to detect Claude Code state and extract responses."""
from __future__ import annotations

import re
from enum import Enum

ANSI_ESCAPE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
_BOX_CHARS = str.maketrans("", "", "╭╮╰╯│─╴╸╼╽╾╿┤├┼┴┬┐└┘┌╔╗╚╝║═╟╠╡╢╣╤╥╦╧╨╩╪╫╬")
_SPINNER = frozenset("⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏")


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
    # bare prompt
    if re.fullmatch(r">?\s*", line):
        return True
    # status-only characters
    if re.fullmatch(r"[✓✗●◆→⟹⮕\s]+", line):
        return True
    if re.fullmatch(r"esc to interrupt", line, re.I):
        return True
    return False


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
            result.append(c)

    # Trim leading/trailing blanks
    while result and not result[0]:
        result.pop(0)
    while result and not result[-1]:
        result.pop()

    return "\n".join(result)
