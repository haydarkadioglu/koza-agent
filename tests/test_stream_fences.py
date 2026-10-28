"""Unit tests for utils.stream_fences (fence-safe streaming helpers)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.stream_fences import ensure_closed_fences, open_fence_language, split_fenced


def _well_formed(text: str) -> bool:
    return text.count("```") % 2 == 0


class TestEnsureClosedFences:
    def test_balanced_text_untouched(self):
        text = "Run `ls`:\n```bash\nls -la\n```\nDone."
        assert ensure_closed_fences(text) == text

    def test_closes_odd_fence(self):
        text = "Here:\n```python\nprint('hi')\n"
        out = ensure_closed_fences(text)
        assert out == "Here:\n```python\nprint('hi')\n```"
        assert _well_formed(out)

    def test_closes_odd_inline_backtick(self):
        assert ensure_closed_fences("use `grep") == "use `grep`"

    def test_backticks_inside_fence_are_ignored(self):
        # Fenced block holds `date` plus one stray backtick (3 total, odd).
        text = "Try:\n```bash\necho `date` and a ` stray\n```\nok"
        assert ensure_closed_fences(text) == text

    def test_backticks_inside_unclosed_fence_are_ignored(self):
        text = "Try:\n```bash\necho ` stray"
        assert ensure_closed_fences(text) == "Try:\n```bash\necho ` stray\n```"

    def test_non_str_and_empty_unchanged(self):
        assert ensure_closed_fences(None) is None
        assert ensure_closed_fences(42) == 42
        assert ensure_closed_fences("") == ""


class TestOpenFenceLanguage:
    def test_language_of_open_fence(self):
        assert open_fence_language("a\n```python\nx = 1\n") == "python"

    def test_no_open_fence(self):
        assert open_fence_language("a\n```python\nx = 1\n```\n") == ""
        assert open_fence_language("plain") == ""


class TestSplitFenced:
    def test_short_text_not_split(self):
        assert split_fenced("hello", 100) == ("hello", "")
        assert split_fenced("hello", 0) == ("hello", "")

    def test_splits_at_last_newline_before_limit(self):
        text = "line one\nline two\nline three"
        head, tail = split_fenced(text, 20)
        assert head == "line one\nline two\n"
        assert tail == "line three"
        assert head + tail == text

    def test_falls_back_to_limit_without_newline(self):
        text = "x" * 50
        head, tail = split_fenced(text, 20)
        assert head == "x" * 20
        assert head + tail == text

    def test_never_splits_inside_fence(self):
        text = "Intro paragraph.\n```python\n" + "".join(f"x{i} = {i}\n" for i in range(10)) + "```\nafter\n"
        limit = text.index("x5")  # naive split lands mid-block
        head, tail = split_fenced(text, limit)
        assert _well_formed(head)
        assert _well_formed(tail)
        assert head.startswith("Intro paragraph.\n```python\n")
        assert head.endswith("\n```")
        # The block is closed in the head and re-opened in the tail.
        assert tail.startswith("```python\nx5")
        assert "x5 = 5" not in head
        assert len(head) <= limit + len("\n```")

    def test_head_stays_under_message_cap(self):
        body = "".join(f"value_{i} = {i}\n" for i in range(400))
        text = "Prose.\n```python\n" + body + "```\n"
        head, tail = split_fenced(text, 4000)
        assert len(head) <= 4004
        assert len(tail) <= len(text)  # tail is only smaller when nothing is added
        assert _well_formed(head)
        assert _well_formed(tail)
        assert not head.splitlines()[-1].startswith("value_17")  # not a 30-char head

    def test_overlong_block_closed_and_reopened(self):
        body = "".join(f"value_{i} = {i}\n" for i in range(40))
        text = "```python\n" + body + "```\n"
        head, tail = split_fenced(text, 100)
        assert head.endswith("\n```")
        assert tail.startswith("```python\n")
        assert _well_formed(head)
        assert _well_formed(tail)
        # Every source line survives exactly once across the two halves.
        joined = head + "\n" + tail
        for i in range(40):
            assert joined.count(f"value_{i} = {i}\n") == 1
