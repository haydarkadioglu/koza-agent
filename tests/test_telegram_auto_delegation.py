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
    _register_completion_watcher,
    _process_message,
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
                "bots.telegram.BackgroundTaskManager.create_task",
                return_value="abc12345",
            ) as mock_create:
                with patch("bots.telegram._register_completion_watcher") as mock_watcher:
                    with patch("bots.telegram._get_or_create_agent", return_value=mock_agent):
                        asyncio.run(_process_message(update, context, agent_factory))

                    # Verify create_task was called with the user text
                    mock_create.assert_called_once_with(
                        "implement a REST API for users",
                        tg_module._bot_cfg,
                        ":memory:",
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
                "bots.telegram.BackgroundTaskManager.create_task"
            ) as mock_create:
                with patch("bots.telegram._get_or_create_agent", return_value=mock_agent):
                    asyncio.run(_process_message(update, context, agent_factory))

                    # create_task should NOT be called for non-coding messages
                    mock_create.assert_not_called()
        finally:
            tg_module._bot_cfg = original_cfg


class TestCompletionWatcher:
    """Test _register_completion_watcher behavior."""

    def test_watcher_sends_done_notification(self):
        """When task completes, watcher sends done notification.

        **Validates: Requirements 3.3**
        """
        mock_loop = asyncio.new_event_loop()
        mock_bot = MagicMock()
        mock_bot.send_message = AsyncMock()

        with patch(
            "bots.telegram.BackgroundTaskManager.get_status",
            return_value={"status": "done", "id": "test123", "goal": "test"},
        ):
            with patch(
                "bots.telegram.BackgroundTaskManager.get_summary",
                return_value="Task completed successfully",
            ):
                _register_completion_watcher("test123", 99999, mock_bot, loop=mock_loop)
                # Give the watcher thread time to poll and send
                time.sleep(6)

        mock_loop.close()

    def test_watcher_sends_error_notification(self):
        """When task errors, watcher sends error notification.

        **Validates: Requirements 3.4**
        """
        mock_loop = asyncio.new_event_loop()
        mock_bot = MagicMock()
        mock_bot.send_message = AsyncMock()

        mock_task = MagicMock()
        mock_task.error_message = "Something went wrong"

        with patch(
            "bots.telegram.BackgroundTaskManager.get_status",
            return_value={"status": "error", "id": "test456", "goal": "test"},
        ):
            with patch(
                "bots.telegram._background_tasks",
                {"test456": mock_task},
            ):
                _register_completion_watcher("test456", 99999, mock_bot, loop=mock_loop)
                # Give the watcher thread time to poll and send
                time.sleep(6)

        mock_loop.close()

    def test_watcher_exits_on_cancelled(self):
        """When task is cancelled, watcher exits without sending notification.

        **Validates: Requirements 3.4**
        """
        mock_loop = asyncio.new_event_loop()
        mock_bot = MagicMock()
        mock_bot.send_message = AsyncMock()

        with patch(
            "bots.telegram.BackgroundTaskManager.get_status",
            return_value={"status": "cancelled", "id": "test789", "goal": "test"},
        ):
            _register_completion_watcher("test789", 99999, mock_bot, loop=mock_loop)
            # Give the watcher thread time to poll
            time.sleep(6)

        mock_loop.close()

    def test_watcher_spawns_daemon_thread(self):
        """Watcher thread is a daemon thread so it doesn't block process exit."""
        mock_loop = asyncio.new_event_loop()
        mock_bot = MagicMock()

        initial_threads = threading.active_count()

        with patch(
            "bots.telegram.BackgroundTaskManager.get_status",
            side_effect=[{"status": "running"}, {"status": "done"}],
        ):
            with patch(
                "bots.telegram.BackgroundTaskManager.get_summary",
                return_value="done",
            ):
                _register_completion_watcher("test_daemon", 99999, mock_bot, loop=mock_loop)
                time.sleep(0.1)  # Let thread start

                # Find the watcher thread
                watcher_threads = [
                    t for t in threading.enumerate()
                    if t.name == "tg-watcher-test_daemon"
                ]
                assert len(watcher_threads) == 1
                assert watcher_threads[0].daemon is True

        mock_loop.close()
