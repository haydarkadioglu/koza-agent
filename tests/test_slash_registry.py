"""Unit tests for cli.slash_registry (shared slash-command vocabulary)."""
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cli.slash_registry import (
    COMMANDS,
    command_names,
    completion_candidates,
    find_command,
    help_rows,
    help_text,
    hint_text,
    is_known_command,
    looks_like_slash_command,
    suggest_command,
    unknown_command_message,
)

_CLI_HANDLED = {
    "help", "sessions", "save", "title", "retry", "undo", "history", "clear", "reset",
    "provider", "model", "kanban", "memory", "tools", "plugins", "plugin", "skills",
    "compress", "mode", "swarm", "self-improve", "google-login", "anthropic-login",
    "codex-login", "email-setup", "email-log", "exit",
}


def _cli_usages():
    return [c.usage for c in COMMANDS if "cli" in c.surfaces]


class TestRegistryInvariants:
    def test_names_and_aliases_unique(self):
        words = [w for c in COMMANDS for w in (c.name, *c.aliases)]
        assert len(words) == len(set(words))

    def test_usage_matches_name(self):
        for c in COMMANDS:
            assert re.fullmatch(rf"/{re.escape(c.name)}( \S.*)?", c.usage), c.usage

    def test_descriptions_single_line(self):
        for c in COMMANDS:
            assert c.description.strip()
            assert "\n" not in c.description
            assert not c.description.endswith(".")

    def test_surfaces_valid_and_populated(self):
        for c in COMMANDS:
            assert c.surfaces and set(c.surfaces) <= {"cli", "tui", "bot"}
        for surface in ("cli", "tui", "bot"):
            assert command_names(surface)

    def test_cli_if_chain_coverage(self):
        assert _CLI_HANDLED <= set(command_names("cli"))


class TestFindCommand:
    @pytest.mark.parametrize("text", ["save", "/save", "/save my title", "/SAVE", "  /Save x "])
    def test_forms(self, text):
        assert find_command(text).name == "save"

    @pytest.mark.parametrize("text,name", [("/?", "help"), ("quit", "exit"), ("/claude-login", "anthropic-login")])
    def test_aliases(self, text, name):
        assert find_command(text).name == name

    def test_tui_only_hidden_on_cli(self):
        assert find_command("/tasks", surface="cli") is None
        assert find_command("/tasks", surface="tui").name == "tasks"

    @pytest.mark.parametrize("text", ["", "/", "  ", "/nope", None, 42])
    def test_garbage_returns_none(self, text):
        assert find_command(text) is None


def test_is_known_command():
    assert is_known_command("/retry", surface="cli")
    assert is_known_command("/help", surface="bot")
    assert not is_known_command("/clera", surface="cli")
    assert not is_known_command("hello", surface="cli")
    assert not is_known_command("/save", surface="bot")


class TestCompletion:
    def test_prefix_s(self):
        out = completion_candidates("/s", surface="cli")
        for usage in ("/save [title]", "/sessions", "/skills", "/self-improve"):
            assert usage in out
        assert "/model [name]" not in out
        assert out == sorted(out)

    def test_lone_slash_returns_all_cli(self):
        assert completion_candidates("/", surface="cli") == sorted(_cli_usages())

    def test_no_match(self):
        assert completion_candidates("/zzz", surface="cli") == []

    def test_surface_filter(self):
        assert "/status" not in completion_candidates("/st", surface="cli")
        assert "/status" in completion_candidates("/st", surface="tui")


def test_suggest_command():
    assert "/clear" in suggest_command("/clera")
    assert suggest_command("/zzzz") == []


class TestLooksLikeCommand:
    @pytest.mark.parametrize("text", ["/help", "/?", "/save my title", "/self-improve", "/email-setup now"])
    def test_true_for_commands(self, text):
        assert looks_like_slash_command(text)

    @pytest.mark.parametrize("text", [
        "",
        "  ",
        "/",
        "merhaba",
        "/etc/hosts is broken",
        "/usr/local/bin/python",
        "/" + "x" * 40,
        None,
        42,
    ])
    def test_false_for_prose_paths_and_garbage(self, text):
        assert not looks_like_slash_command(text)

    def test_strips_surrounding_whitespace(self):
        assert looks_like_slash_command("  /mode coding  ")

    @pytest.mark.parametrize("usage", [c.usage for c in COMMANDS if "cli" in c.surfaces])
    def test_every_registered_usage_passes_the_guard(self, usage):
        """The unknown-command guard must never swallow a command the CLI handles."""
        assert looks_like_slash_command(usage)
        assert is_known_command(usage, surface="cli")


class TestUnknownMessage:
    def test_with_suggestion(self):
        msg = unknown_command_message("/clera now")
        assert "/clera" in msg and "Did you mean /clear?" in msg and "Type /help" in msg

    def test_without_suggestion(self):
        msg = unknown_command_message("/zzzz")
        assert "Did you mean" not in msg and "Type /help" in msg

    def test_truncates_long_token(self):
        msg = unknown_command_message("/" + "x" * 500)
        assert "x" * 40 not in msg
        assert len(msg) < 120


class TestHelp:
    def test_cli_text_lists_every_usage(self):
        text = help_text("cli")
        for usage in _cli_usages():
            assert usage in text
        assert not text.endswith("\n")

    def test_bot_text(self):
        text = help_text("bot")
        assert "/help" in text and "/save" not in text

    def test_translate_applied_to_description_only(self):
        rows = help_rows("cli", translate=str.upper)
        assert ("/help", "SHOW THIS HELP") in rows

    def test_hint_text(self):
        assert hint_text("cli").startswith("Commands: /help")


def test_layout_completer_uses_registry():
    try:
        from cli.ui import _layout
    except ImportError as e:  # pragma: no cover - environment dependent
        pytest.skip(f"cli.ui._layout not importable: {e}")
    assert _layout._SLASH_CMDS == _cli_usages()
