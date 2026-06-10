"""Unit tests for parser.py — no tmux required."""
import pytest

from claude_tmux_mcp.parser import (
    SessionState,
    _is_chrome,
    clean_line,
    detect_state,
    extract_response,
    strip_ansi,
)

# ---------------------------------------------------------------------------
# Fixtures / sample content
# ---------------------------------------------------------------------------

IDLE_PANE = """\
╭──────────────────────────────────────╮
│ Claude: Hello! I can help with that. │
╰──────────────────────────────────────╯
>
"""

BUSY_PANE = """\
╭──────────────────────────────────────╮
│ Thinking about your question...      │
│                                      │
╰──────────────────────────────────────╯
esc to interrupt
"""

SPINNER_PANE = "Some content\n⠋ Processing...\n"

ANSI_TEXT = "\x1b[32mGreen\x1b[0m \x1b[1mBold\x1b[0m plain"


# ---------------------------------------------------------------------------
# strip_ansi
# ---------------------------------------------------------------------------

def test_strip_ansi_removes_sequences():
    assert strip_ansi(ANSI_TEXT) == "Green Bold plain"


def test_strip_ansi_idempotent():
    plain = "hello world"
    assert strip_ansi(plain) == plain


# ---------------------------------------------------------------------------
# clean_line
# ---------------------------------------------------------------------------

def test_clean_line_strips_box_chars():
    assert clean_line("│  Hello there  │") == "Hello there"


def test_clean_line_strips_ansi_and_box():
    assert clean_line("\x1b[1m╭─ Claude ─╮\x1b[0m") == "Claude"


# ---------------------------------------------------------------------------
# detect_state
# ---------------------------------------------------------------------------

def test_detect_idle():
    assert detect_state(IDLE_PANE) == SessionState.IDLE


def test_detect_busy_esc_to_interrupt():
    assert detect_state(BUSY_PANE) == SessionState.BUSY


def test_detect_busy_spinner():
    assert detect_state(SPINNER_PANE) == SessionState.BUSY


def test_detect_busy_ansi_wrapped():
    content = f"\x1b[2mesc to interrupt\x1b[0m"
    assert detect_state(content) == SessionState.BUSY


def test_detect_busy_case_insensitive():
    assert detect_state("ESC TO INTERRUPT\n") == SessionState.BUSY


# ---------------------------------------------------------------------------
# _is_chrome
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("line", [
    "",
    ">",
    "> ",
    "   ",
    "✓",
    "●◆→",
    "esc to interrupt",
    "ESC TO INTERRUPT",
])
def test_is_chrome_true(line):
    assert _is_chrome(line)


@pytest.mark.parametrize("line", [
    "Hello world",
    "2+2 equals 4",
    "Done! Here is the result.",
])
def test_is_chrome_false(line):
    assert not _is_chrome(line)


# ---------------------------------------------------------------------------
# extract_response
# ---------------------------------------------------------------------------

def test_extract_response_basic():
    before = "User: hello\n"
    after = (
        "User: hello\n"
        "User: what is 2+2?\n"
        "Claude: 2+2 equals 4.\n"
        "> \n"
    )
    result = extract_response(before, after, "what is 2+2?")
    assert "4" in result
    # Prompt itself and chrome should not appear
    assert ">" not in result
    assert "what is 2+2?" not in result


def test_extract_response_strips_box_drawing():
    before = ""
    after = "User: hi\n╭───╮\n│ Claude: Hello!\n╰───╯\n> \n"
    result = extract_response(before, after, "hi")
    assert "Claude: Hello!" in result
    assert "╭" not in result
    assert "╰" not in result


def test_extract_response_empty_before():
    before = ""
    after = "hello prompt\nThe answer is 42.\n> \n"
    result = extract_response(before, after, "hello prompt")
    assert "42" in result


def test_extract_response_no_trailing_blank():
    before = "old\n"
    after = "old\nnew prompt\nAnswer here.\n\n\n"
    result = extract_response(before, after, "new prompt")
    assert not result.endswith("\n")
    assert "Answer here." in result


def test_extract_response_fallback_when_prompt_not_found():
    before = ""
    after = "Some content\nResponse line.\n"
    # prompt not in 'after', should still return something reasonable
    result = extract_response(before, after, "zzz-not-present")
    assert "Response line." in result
