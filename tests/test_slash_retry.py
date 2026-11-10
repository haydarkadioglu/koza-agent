"""Tests for cli.slash_result — explicit slash outcomes and the /retry engine (K-41)."""
import copy

from cli.slash_result import (
    SlashAction,
    SlashResult,
    outcome_text,
    retry_last_user_message,
)

SYSTEM = {"role": "system", "content": "You are Koza."}


class TestSlashResult:
    def test_handled(self):
        r = SlashResult.handled()
        assert r.action is SlashAction.HANDLED
        assert r.text is None

    def test_exit_app(self):
        r = SlashResult.exit_app()
        assert r.action is SlashAction.EXIT
        assert r.text is None

    def test_not_command(self):
        r = SlashResult.not_command()
        assert r.action is SlashAction.NOT_COMMAND
        assert r.text is None

    def test_resubmit(self):
        r = SlashResult.resubmit("hello")
        assert r.action is SlashAction.RESUBMIT
        assert r.text == "hello"


class TestOutcomeText:
    def test_not_command_returns_typed_line(self):
        assert outcome_text(SlashResult.not_command(), "what is 2+2?") == "what is 2+2?"

    def test_resubmit_returns_result_text_not_typed(self):
        assert outcome_text(SlashResult.resubmit("hello"), "/retry") == "hello"

    def test_handled_returns_none(self):
        assert outcome_text(SlashResult.handled(), "/clear") is None

    def test_exit_returns_none(self):
        assert outcome_text(SlashResult.exit_app(), "exit") is None

    def test_resubmit_empty_returns_none(self):
        assert outcome_text(SlashResult.resubmit(""), "/retry") is None
        assert outcome_text(SlashResult(SlashAction.RESUBMIT, None), "/retry") is None


class TestRetryLastUserMessage:
    def test_single_turn(self):
        msgs = [SYSTEM, {"role": "user", "content": "hello"}, {"role": "assistant", "content": "hi"}]
        assert retry_last_user_message(msgs) == "hello"
        assert msgs == [SYSTEM]

    def test_multi_turn_keeps_earlier_turns(self):
        msgs = [
            SYSTEM,
            {"role": "user", "content": "a"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "b"},
            {"role": "assistant", "content": "b1"},
        ]
        assert retry_last_user_message(msgs) == "b"
        assert msgs == [
            SYSTEM,
            {"role": "user", "content": "a"},
            {"role": "assistant", "content": "a1"},
        ]

    def test_trailing_tool_messages_dropped(self):
        msgs = [
            SYSTEM,
            {"role": "user", "content": "list files"},
            {"role": "assistant", "content": "", "tool_calls": [{"id": "t1"}]},
            {"role": "tool", "tool_call_id": "t1", "content": "a.txt"},
            {"role": "assistant", "content": "a.txt"},
            {"role": "tool", "tool_call_id": "t2", "content": "late"},
        ]
        assert retry_last_user_message(msgs) == "list files"
        assert msgs == [SYSTEM]

    def test_list_of_parts_content(self):
        msgs = [
            SYSTEM,
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "describe "},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,xx"}},
                    {"type": "text", "text": "this"},
                ],
            },
            {"role": "assistant", "content": "a cat"},
        ]
        assert retry_last_user_message(msgs) == "describe this"
        assert msgs == [SYSTEM]

    def test_empty_history_returns_none(self):
        msgs = []
        assert retry_last_user_message(msgs) is None
        assert msgs == []

    def test_system_only_returns_none_and_does_not_mutate(self):
        msgs = [SYSTEM]
        assert retry_last_user_message(msgs) is None
        assert msgs == [SYSTEM]

    def test_whitespace_only_user_is_skipped(self):
        msgs = [
            SYSTEM,
            {"role": "user", "content": "real"},
            {"role": "assistant", "content": "ok"},
            {"role": "user", "content": "   "},
            {"role": "assistant", "content": "?"},
        ]
        assert retry_last_user_message(msgs) == "real"
        assert msgs == [SYSTEM]

    def test_no_eligible_user_does_not_mutate(self):
        msgs = [SYSTEM, {"role": "user", "content": "  "}, {"role": "assistant", "content": "x"}]
        before = copy.deepcopy(msgs)
        assert retry_last_user_message(msgs) is None
        assert msgs == before

    def test_system_message_never_removed(self):
        msgs = [{"role": "system", "content": "sys"}, {"role": "assistant", "content": "x"}]
        assert retry_last_user_message(msgs) is None
        assert msgs[0] == {"role": "system", "content": "sys"}

    def test_resubmit_reproduces_user_turn_once(self):
        original = [
            SYSTEM,
            {"role": "user", "content": "a"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "b"},
            {"role": "assistant", "content": "b1"},
        ]
        msgs = copy.deepcopy(original)
        text = retry_last_user_message(msgs)
        msgs.append({"role": "user", "content": text})
        assert msgs == original[:-1]
        assert sum(1 for m in msgs if m["role"] == "user" and m["content"] == "b") == 1
