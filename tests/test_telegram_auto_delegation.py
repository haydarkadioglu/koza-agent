"""Unit tests for Telegram auto-delegation and completion watcher.

Tests the integration between _process_message, _is_coding_task,
BackgroundTaskManager.create_task, and _register_completion_watcher.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4**
"""
import sys
import os
import asyncio
import threading
import time
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from bots.telegram import (
    _completion_watcher_loop,
    _process_message,
    _register_completion_watcher,
)


class TestAutoDetectionIntegration:
    """Test that _process_message delegates coding tasks to background."""

    def test_coding_task_sends_confirmation_and_returns_early(self):
        """When router says delegate_to_background=True, _process_message sends confirmation
        with task_id and goal, then returns without streaming.

        **Validates: Requirements 3.1, 3.2**
        """
        import bots.telegram as tg_module
        from router import RoutingDecision

        # Set up module-level config
        original_cfg = tg_module._bot_cfg
        tg_module._bot_cfg = {"db_path": ":memory:", "provider": "test"}

        try:
            # Mock update and context
            update = MagicMock()
            update.message.chat_id = 12345
            update.message.text = "implement a REST API for users"
            update.message.caption = None
            update.message.photo = None
            update.message.document = None
            update.message.video = None
            update.message.audio = None
            update.message.voice = None
            update.edited_message = None

            context = MagicMock()
            context.bot.send_message = AsyncMock()

            # Mock agent with router that says delegate
            mock_agent = MagicMock()
            mock_agent._busy = False
            mock_agent._router = MagicMock()
            mock_agent._router.classify.return_value = RoutingDecision(delegate_to_background=True)
            mock_agent.permission_callback = None

            agent_factory = MagicMock(return_value=mock_agent)

            with patch(
                "skills.agents.spawn_subagent",
                return_value="Sub-agent abc12345 launched (background)",
            ) as mock_spawn:
                with patch("skills.agents.notifier.SubAgentNotifier.start") as mock_notifier:
                    with patch("bots.telegram._get_or_create_agent", return_value=mock_agent):
                        asyncio.run(_process_message(update, context, agent_factory))

                    # Verify spawn_subagent was called with the user text
                    mock_spawn.assert_called_once_with(
                        "implement a REST API for users",
                        wait=False,
                    )

                    # Verify confirmation message was sent
                    context.bot.send_message.assert_called_once()
                    call_kwargs = context.bot.send_message.call_args[1]
                    assert call_kwargs["chat_id"] == 12345
                    assert "abc12345" in call_kwargs["text"]
                    assert "implement a REST API for users" in call_kwargs["text"]
        finally:
            tg_module._bot_cfg = original_cfg

    def test_non_coding_task_proceeds_normally(self):
        """When router says delegate_to_background=False, normal processing occurs.

        **Validates: Requirements 3.1**
        """
        import bots.telegram as tg_module
        from router import RoutingDecision

        original_cfg = tg_module._bot_cfg
        tg_module._bot_cfg = {"db_path": ":memory:", "provider": "test"}

        try:
            update = MagicMock()
            update.message.chat_id = 12345
            update.message.text = "what is the weather today?"
            update.message.caption = None
            update.message.photo = None
            update.message.document = None
            update.message.video = None
            update.message.audio = None
            update.message.voice = None
            update.edited_message = None

            context = MagicMock()
            context.bot.send_message = AsyncMock()
            context.bot.send_chat_action = AsyncMock()

            mock_agent = MagicMock()
            mock_agent._busy = False
            mock_agent._router = MagicMock()
            mock_agent._router.classify.return_value = RoutingDecision(delegate_to_background=False)
            mock_agent.stream_chat = MagicMock(return_value=iter([{"type": "text", "token": "Hello"}]))

            agent_factory = MagicMock(return_value=mock_agent)

            with patch(
                "skills.agents.spawn_subagent"
            ) as mock_spawn:
                with patch("bots.telegram._get_or_create_agent", return_value=mock_agent):
                    asyncio.run(_process_message(update, context, agent_factory))

                    # spawn_subagent should NOT be called for non-coding messages
                    mock_spawn.assert_not_called()
        finally:
            tg_module._bot_cfg = original_cfg


class _FakeBot:
    """Bot whose send_message is a real coroutine that records each call."""

    def __init__(self):
        self.calls = []
        self.sent = threading.Event()

    async def send_message(self, chat_id, text):
        self.calls.append({"chat_id": chat_id, "text": text})
        self.sent.set()


@pytest.fixture
def running_loop():
    """A real event loop running in a daemon thread, stopped and closed on teardown."""
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True, name="tg-test-loop")
    thread.start()
    try:
        yield loop
    finally:
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=2)
        assert not thread.is_alive()
        loop.close()


def _drain(loop):
    """Wait until every callback already queued on ``loop`` has run."""
    async def _noop():
        return None

    asyncio.run_coroutine_threadsafe(_noop(), loop).result(timeout=2)


def _no_sleep(_seconds):
    return None


class TestCompletionWatcher:
    """Test _completion_watcher_loop / _register_completion_watcher behavior."""

    def test_watcher_sends_done_notification(self, running_loop):
        """When task completes, watcher sends exactly one done notification.

        **Validates: Requirements 3.3**
        """
        bot = _FakeBot()

        with patch(
            "bots.telegram.BackgroundTaskManager.get_status",
            return_value={"status": "done", "id": "test123", "goal": "test"},
        ), patch(
            "bots.telegram.BackgroundTaskManager.get_summary",
            return_value="build finished",
        ):
            _completion_watcher_loop(
                "test123", 99999, bot, running_loop,
                poll_interval=0, sleeper=_no_sleep,
            )

        assert bot.sent.wait(timeout=2)
        _drain(running_loop)
        assert len(bot.calls) == 1
        assert bot.calls[0]["chat_id"] == 99999
        assert "test123" in bot.calls[0]["text"]
        assert "build finished" in bot.calls[0]["text"]

    def test_watcher_sends_error_notification(self, running_loop):
        """When task errors, watcher sends exactly one error notification.

        **Validates: Requirements 3.4**
        """
        bot = _FakeBot()

        mock_task = MagicMock()
        mock_task.error_message = "Something went wrong"

        with patch(
            "bots.telegram.BackgroundTaskManager.get_status",
            return_value={"status": "error", "id": "test456", "goal": "test"},
        ), patch(
            "bots.telegram._background_tasks",
            {"test456": mock_task},
        ):
            _completion_watcher_loop(
                "test456", 99999, bot, running_loop,
                poll_interval=0, sleeper=_no_sleep,
            )

        assert bot.sent.wait(timeout=2)
        _drain(running_loop)
        assert len(bot.calls) == 1
        assert bot.calls[0]["chat_id"] == 99999
        assert "test456" in bot.calls[0]["text"]
        assert "Something went wrong" in bot.calls[0]["text"]

    def test_watcher_exits_on_cancelled(self, running_loop):
        """When task is cancelled, watcher returns without sending a notification.

        **Validates: Requirements 3.4**
        """
        bot = _FakeBot()

        with patch(
            "bots.telegram.BackgroundTaskManager.get_status",
            return_value={"status": "cancelled", "id": "test789", "goal": "test"},
        ) as mock_status:
            # Returns (rather than hanging) because cancelled is terminal.
            _completion_watcher_loop(
                "test789", 99999, bot, running_loop,
                poll_interval=0, sleeper=_no_sleep,
            )

        _drain(running_loop)
        assert mock_status.call_count == 1
        assert bot.calls == []
        assert not bot.sent.is_set()

    def test_watcher_polls_until_terminal(self, running_loop):
        """A running status keeps polling; only the terminal done status sends."""
        bot = _FakeBot()
        sleeps = []

        with patch(
            "bots.telegram.BackgroundTaskManager.get_status",
            side_effect=[{"status": "running"}, {"status": "done"}],
        ) as mock_status, patch(
            "bots.telegram.BackgroundTaskManager.get_summary",
            return_value="build finished",
        ):
            _completion_watcher_loop(
                "test_poll", 99999, bot, running_loop,
                poll_interval=0, sleeper=sleeps.append,
            )

        assert bot.sent.wait(timeout=2)
        _drain(running_loop)
        assert mock_status.call_count == 2
        assert sleeps == [0, 0]
        assert len(bot.calls) == 1
        assert "test_poll" in bot.calls[0]["text"]
        assert "build finished" in bot.calls[0]["text"]

    def test_watcher_spawns_daemon_thread(self, running_loop):
        """Watcher thread is a daemon thread so it doesn't block process exit."""
        bot = _FakeBot()
        release = threading.Event()
        statuses = iter([{"status": "running"}, {"status": "done"}])

        def _get_status(_task_id):
            # Hold the watcher on its first poll so the thread is observably alive.
            release.wait(timeout=2)
            return next(statuses)

        with patch(
            "bots.telegram.BackgroundTaskManager.get_status",
            side_effect=_get_status,
        ), patch(
            "bots.telegram.BackgroundTaskManager.get_summary",
            return_value="done",
        ):
            _register_completion_watcher(
                "test_daemon", 99999, bot, loop=running_loop, poll_interval=0.01,
            )

            deadline = time.monotonic() + 2
            watcher_threads = []
            while not watcher_threads and time.monotonic() < deadline:
                watcher_threads = [
                    t for t in threading.enumerate()
                    if t.name == "tg-watcher-test_daemon"
                ]

            assert len(watcher_threads) == 1
            assert watcher_threads[0].daemon is True

            release.set()
            watcher_threads[0].join(timeout=2)
            assert not watcher_threads[0].is_alive()

        assert bot.sent.wait(timeout=2)
        _drain(running_loop)
        assert len(bot.calls) == 1
