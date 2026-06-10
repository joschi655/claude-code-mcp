"""Unit tests for parser.py — no tmux required."""
import pytest

from claude_code_mcp.parser import (
    SessionState,
    _is_chrome,
    clean_line,
    detect_state,
    extract_response,
    is_claude_ui_present,
    is_startup_screen,
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

STARTUP_PANE = """\
Claude Code v2.1.92
Tips for getting started
Welcome back Oskar!
We recommend medium effort for Opus
Effort determines how long Claude thinks for when completing your task.
○ low · ◐ medium · ● high
❯ 1. ◐ Medium (recommended)
2. ● High
3. ○ Low
"""


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
    "❯",
    "esc to interrupt",
    "ESC TO INTERRUPT",
    "? for shortcuts                                  /buddy",
    "✗ Auto-update failed · Try claude doctor or npm i -g @anthropic-ai/claude-code",
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


def test_extract_response_strips_leading_bullet():
    """Leading status chars like ● are stripped from content lines."""
    before = ""
    after = "run test\n● TEST_OK\n❯\n? for shortcuts   /buddy\n"
    result = extract_response(before, after, "run test")
    assert result == "TEST_OK"
    assert "●" not in result
    assert "❯" not in result
    assert "shortcuts" not in result


def test_extract_response_filters_auto_update_banner():
    before = ""
    after = "check\nThe answer is 7.\n✗ Auto-update failed · Try claude doctor\n>\n"
    result = extract_response(before, after, "check")
    assert "7" in result
    assert "Auto-update" not in result


def test_extract_response_fallback_when_prompt_not_found():
    before = ""
    after = "Some content\nResponse line.\n"
    # prompt not in 'after', should still return something reasonable
    result = extract_response(before, after, "zzz-not-present")
    assert "Response line." in result


# ---------------------------------------------------------------------------
# is_startup_screen
# ---------------------------------------------------------------------------

def test_is_startup_screen_full_pane():
    assert is_startup_screen(STARTUP_PANE)


def test_is_startup_screen_effort_option_line():
    assert is_startup_screen("❯ 1. ◐ Medium (recommended)\n")


def test_is_startup_screen_effort_text():
    assert is_startup_screen("Effort determines how long Claude thinks\n")


def test_is_startup_screen_options_line():
    assert is_startup_screen("○ low · ◐ medium · ● high\n")


def test_is_startup_screen_normal_idle_is_false():
    assert not is_startup_screen(IDLE_PANE)


def test_is_startup_screen_empty_is_false():
    assert not is_startup_screen("")


def test_is_startup_screen_busy_is_false():
    assert not is_startup_screen(BUSY_PANE)


def test_is_startup_screen_strips_ansi():
    ansi_startup = "\x1b[1m❯ 1.\x1b[0m ◐ Medium (recommended)\n"
    assert is_startup_screen(ansi_startup)


def test_detect_state_startup_screen_is_idle():
    # The startup screen has no spinner and no "esc to interrupt" — it reads as IDLE.
    # is_startup_screen() is the correct gate, not detect_state().
    assert detect_state(STARTUP_PANE) == SessionState.IDLE


# ---------------------------------------------------------------------------
# is_claude_ui_present
# ---------------------------------------------------------------------------

def test_is_claude_ui_present_false_for_raw_shell():
    """A bare shell prompt is not Claude UI."""
    assert not is_claude_ui_present("ubuntu@ubuntu:~/projects$ ")
    assert not is_claude_ui_present("")
    assert not is_claude_ui_present("\n$ \n")
    assert not is_claude_ui_present("ubuntu@host:~$ claude\n")


def test_is_claude_ui_present_startup_screen():
    assert is_claude_ui_present(STARTUP_PANE)


def test_is_claude_ui_present_effort_option_line():
    assert is_claude_ui_present("❯ 1. ◐ Medium (recommended)\n")


def test_is_claude_ui_present_esc_to_interrupt():
    assert is_claude_ui_present("esc to interrupt\n⠙ Thinking...\n")


def test_is_claude_ui_present_spinner_only():
    assert is_claude_ui_present("⠋ Loading...\n")


def test_is_claude_ui_present_claude_code_branding():
    assert is_claude_ui_present("Claude Code v2.1.92\nTips for getting started\n")


def test_is_claude_ui_present_claude_ai():
    assert is_claude_ui_present("claude.ai\n>\n")


def test_is_claude_ui_present_welcome_back():
    assert is_claude_ui_present("Welcome back Oskar!\n>\n")


def test_is_claude_ui_present_tips():
    assert is_claude_ui_present("Tips for getting started\n")


def test_is_claude_ui_present_strips_ansi():
    assert is_claude_ui_present("\x1b[1mClaude Code\x1b[0m v2.0\n")


def test_is_claude_ui_present_idle_pane_with_branding():
    # An idle pane that previously showed Claude content is "present"
    assert is_claude_ui_present("Claude Code v2.0\n" + IDLE_PANE)
