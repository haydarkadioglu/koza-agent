"""Unit tests for Telegram voice-note intake in bots.telegram._process_message.

The telegram boundary is fully mocked; transcription is patched, so every
test stays offline and fast.
"""
import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import bots.telegram as tg_module
from bots.telegram import _process_message
from router import RoutingDecision


@pytest.fixture
def bot_cfg(tmp_path):
    original = tg_module._bot_cfg
    cfg = {
        "db_path": ":memory:",
        "provider": "test",
        "workspace_path": str(tmp_path),
        "messaging": {"telegram": {"voice_notes": {"enabled": True, "max_seconds": 300, "timeout_seconds": 5}}},
    }
    tg_module._bot_cfg = cfg
    tg_module._recent_attachments_by_chat.pop(4242, None)
    try:
        yield cfg
    finally:
        tg_module._bot_cfg = original
        tg_module._recent_attachments_by_chat.pop(4242, None)


def _voice_update(duration: int = 7):
    update = MagicMock()
    msg = update.message
    msg.chat_id = 4242
    msg.message_id = 1
    msg.text = None
    msg.caption = None
    msg.photo = None
    msg.document = None
    msg.video = None
    msg.audio = None
    msg.voice = MagicMock(file_id="AwACAgIAAxkBAAIB", duration=duration)
    update.edited_message = None
    return update


def _context():
    context = MagicMock()
    context.bot.send_message = AsyncMock()
    context.bot.send_chat_action = AsyncMock()
    context.bot.set_message_reaction = AsyncMock()

    def _download(path):
        with open(path, "wb") as f:
            f.write(b"OggS")

    tg_file = MagicMock()
    tg_file.download_to_drive = AsyncMock(side_effect=_download)
    context.bot.get_file = AsyncMock(return_value=tg_file)
    return context


def _agent():
    agent = MagicMock()
    agent._busy = False
    agent._router = MagicMock()
    agent._router.classify.return_value = RoutingDecision(delegate_to_background=False)
    agent.stream_chat = MagicMock(return_value=iter([{"type": "text", "token": "OK"}]))
    return agent


def _run(update, context, agent):
    with patch("bots.telegram._get_or_create_agent", return_value=agent), \
         patch("config.load_config", return_value={"messaging": {"telegram": {"chat_id": "4242"}}}):
        asyncio.run(_process_message(update, context, MagicMock(return_value=agent)))


def _sent_texts(context):
    return [c.kwargs.get("text", "") for c in context.bot.send_message.call_args_list]


def test_voice_note_transcribed_and_sent_to_agent(bot_cfg, tmp_path):
    update, context, agent = _voice_update(), _context(), _agent()
    with patch("skills.voice.transcribe_audio_file", return_value="open the pod bay doors") as stt:
        _run(update, context, agent)

    stt.assert_called_once()
    assert stt.call_args.args[0].endswith("voice_AwACAgIA.ogg")
    agent.stream_chat.assert_called_once()
    user_text = agent.stream_chat.call_args.args[0]
    assert "open the pod bay doors" in user_text
    assert "duration=7s" in user_text
    assert (tmp_path / "downloads" / "telegram" / "voice_AwACAgIA.ogg").exists()


def test_voice_notes_disabled(bot_cfg):
    bot_cfg["messaging"]["telegram"]["voice_notes"]["enabled"] = False
    update, context, agent = _voice_update(), _context(), _agent()
    with patch("skills.voice.transcribe_audio_file") as stt:
        _run(update, context, agent)

    assert any("Voice notes are disabled" in t for t in _sent_texts(context))
    stt.assert_not_called()
    context.bot.get_file.assert_not_called()
    agent.stream_chat.assert_not_called()


def test_transcription_error_reports_and_skips_agent(bot_cfg):
    update, context, agent = _voice_update(), _context(), _agent()
    with patch("skills.voice.transcribe_audio_file", side_effect=RuntimeError("STT provider is not configured")):
        _run(update, context, agent)

    texts = _sent_texts(context)
    assert any("Voice transcription failed: STT provider is not configured" in t for t in texts)
    agent.stream_chat.assert_not_called()


def test_transcription_timeout_reports_and_skips_agent(bot_cfg):
    import time
    bot_cfg["messaging"]["telegram"]["voice_notes"]["timeout_seconds"] = 0.05
    update, context, agent = _voice_update(), _context(), _agent()
    with patch("skills.voice.transcribe_audio_file", side_effect=lambda *a: time.sleep(0.3) or "late"):
        _run(update, context, agent)

    assert any("timed out" in t for t in _sent_texts(context))
    agent.stream_chat.assert_not_called()


def test_empty_transcript_reports_and_skips_agent(bot_cfg):
    update, context, agent = _voice_update(), _context(), _agent()
    with patch("skills.voice.transcribe_audio_file", return_value="   "):
        _run(update, context, agent)

    assert any("empty result" in t for t in _sent_texts(context))
    agent.stream_chat.assert_not_called()


def test_voice_note_too_long(bot_cfg):
    update, context, agent = _voice_update(duration=301), _context(), _agent()
    with patch("skills.voice.transcribe_audio_file") as stt:
        _run(update, context, agent)

    assert any("301s" in t and "300s" in t for t in _sent_texts(context))
    context.bot.get_file.assert_not_called()
    stt.assert_not_called()
    agent.stream_chat.assert_not_called()
