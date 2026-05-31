"""
Telegram bot thread for Koza daemon.

Each Telegram chat_id gets its own Agent instance (isolated session).
Messages stream back to the user in real time (chunked text edits).
"""
import asyncio
import json
import logging
import os
import re
import sqlite3
import threading
from pathlib import Path
from typing import Dict, Callable

from skills.agents.background import BackgroundTaskManager, _background_tasks

logger = logging.getLogger(__name__)

# ── Module-level config reference (set by start_bot_thread) ──────────────────
_bot_cfg: dict | None = None

# ── Telegram conversation history persistence ─────────────────────────────────
# Conversations are persisted to SQLite so context survives bot restarts.
_TG_HISTORY_KEEP = 100   # max messages to persist per chat_id


def _get_db_path() -> str | None:
    if _bot_cfg:
        return _bot_cfg.get("db_path")
    return None


def _ensure_history_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS telegram_history (
               chat_id   INTEGER PRIMARY KEY,
               messages  TEXT NOT NULL,
               updated_at TEXT DEFAULT (datetime('now'))
           )"""
    )
    conn.commit()


def _save_tg_history(chat_id: int, messages: list) -> None:
    """Persist agent message history (excluding system msg) for a chat_id."""
    db_path = _get_db_path()
    if not db_path:
        return
    try:
        # Keep only non-system messages, capped to last _TG_HISTORY_KEEP entries
        history = [m for m in messages if m.get("role") != "system"]
        history = history[-_TG_HISTORY_KEEP:]
        with sqlite3.connect(db_path) as conn:
            _ensure_history_table(conn)
            conn.execute(
                """INSERT INTO telegram_history (chat_id, messages, updated_at)
                   VALUES (?, ?, datetime('now'))
                   ON CONFLICT(chat_id) DO UPDATE SET messages=excluded.messages,
                                                      updated_at=excluded.updated_at""",
                (chat_id, json.dumps(history, ensure_ascii=False)),
            )
            conn.commit()
    except Exception as e:
        logger.debug(f"_save_tg_history failed: {e}")


def _load_tg_history(chat_id: int) -> list:
    """Load persisted message history for a chat_id (returns [] if none)."""
    db_path = _get_db_path()
    if not db_path:
        return []
    try:
        with sqlite3.connect(db_path) as conn:
            _ensure_history_table(conn)
            row = conn.execute(
                "SELECT messages FROM telegram_history WHERE chat_id = ?",
                (chat_id,),
            ).fetchone()
            if row:
                return json.loads(row[0])
    except Exception as e:
        logger.debug(f"_load_tg_history failed: {e}")
    return []


def _strip_markdown(text: str) -> str:
    """Remove markdown formatting from text for clean Telegram display."""
    # Remove headers (## Title → Title)
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    # Remove bold (**text** or __text__ → text)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"__(.+?)__", r"\1", text)
    # Remove italic (*text* or _text_ → text) — careful not to hit underscores in code
    text = re.sub(r"(?<!\w)\*([^*]+?)\*(?!\w)", r"\1", text)
    # Remove inline code (`text` → text)
    text = re.sub(r"`([^`]+?)`", r"\1", text)
    # Remove code block fences (```lang ... ``` → just the code)
    text = re.sub(r"```\w*\n?", "", text)
    # Remove horizontal rules (--- or ***)
    text = re.sub(r"^[-*]{3,}\s*$", "", text, flags=re.MULTILINE)
    # Remove bullet markers (- item → item, * item → item)
    text = re.sub(r"^[\-\*]\s+", "• ", text, flags=re.MULTILINE)
    return text.strip()


# Patterns that the LLM should never generate but sometimes does — strip them out
_ECHO_PATTERNS = re.compile(
    r"(?:"
    r"[✅🔄]\s*Mesajın[ıi]z?\s+alındı[:\s].*?(?:\n|$)"
    r"|Koza\s+AI['']?ya\s+yönlendiriyorum.*?(?:\n|$)"
    r"|Chat\s+ID\s*:\s*\d+\s*(?:\n|$)"
    r"|[✅☑]\s*Mesajını[z]?\s+aldım.*?(?:\n|$)"
    r"|Hemen\s+başlıyorum[…\.]*\s*(?:\n|$)"
    r"|Tabii\s*ki[,\s]+hemen.*?(?:\n|$)"
    r"|Sure[,\s]+let\s+me.*?(?:\n|$)"
    r")",
    re.IGNORECASE | re.MULTILINE,
)


def _sanitize_response(text: str) -> str:
    """Strip any LLM-generated echo/routing messages before sending to Telegram."""
    cleaned = _ECHO_PATTERNS.sub("", text).strip()
    return cleaned if cleaned else text  # if all stripped, return original (shouldn't happen)


# ── LLM-driven routing (replaces keyword-based detection) ────────────────────
# The router is accessed via the agent instance: agent._router.classify(text)
# No more keyword lists here — the LLM decides what's a coding task.


def _register_completion_watcher(task_id: str, chat_id: int, bot, loop=None) -> None:
    """Poll task status and send notification on completion."""
    assert loop is not None, "_register_completion_watcher requires a running event loop"

    def _watcher():
        import time
        while True:
            time.sleep(5)
            status = BackgroundTaskManager.get_status(task_id)
            if not status:
                break
            if status["status"] == "done":
                summary = BackgroundTaskManager.get_summary(task_id)
                msg_text = f"✅ Task {task_id} done:\n{summary}"
                asyncio.run_coroutine_threadsafe(
                    bot.send_message(chat_id=chat_id, text=msg_text),
                    loop,
                )
                break
            elif status["status"] == "error":
                from skills.agents._registry import _subagents
                task_reg = _background_tasks.get(task_id) or _subagents.get(task_id)
                err = (
                    getattr(task_reg, "error_message", None)
                    or (task_reg.get("result", "") if isinstance(task_reg, dict) else "")
                    or "Unknown error"
                )
                msg_text = f"❌ Task {task_id} failed:\n{err}"
                asyncio.run_coroutine_threadsafe(
                    bot.send_message(chat_id=chat_id, text=msg_text),
                    loop,
                )
                break
            elif status["status"] == "cancelled":
                break

    threading.Thread(target=_watcher, daemon=True, name=f"tg-watcher-{task_id}").start()


# chat_id → Agent instance
_agents: Dict[int, object] = {}
_agents_lock = threading.Lock()


# Tools that require explicit user approval via inline buttons.
# Everything else is auto-approved to avoid spamming the chat.
_TOOLS_REQUIRING_APPROVAL = {
    "delete_file", "delete_directory",
    "send_email", "git_push", "deploy", "install_package",
}


def _make_permission_callback(chat_id: int, bot, loop, kb_manager):
    """Create a permission callback that uses inline buttons for tool confirmation.

    Only tools in _TOOLS_REQUIRING_APPROVAL prompt the user. All other tools
    are auto-approved to keep the chat clean.
    """

    def permission_callback(tool_name: str, tool_args: dict) -> bool:
        """Block until user approves/rejects via inline button (or timeout)."""
        # Auto-approve safe tools — no inline button needed
        if tool_name not in _TOOLS_REQUIRING_APPROVAL:
            return True

        conf_id, text, keyboard, future = kb_manager.build_tool_confirmation_kb(
            tool_name, tool_args, loop
        )

        # Send confirmation message from the agent's worker thread
        send_coro = bot.send_message(
            chat_id=chat_id, text=text, reply_markup=keyboard,
            parse_mode="Markdown"
        )
        msg_future = asyncio.run_coroutine_threadsafe(send_coro, loop)
        try:
            sent_msg = msg_future.result(timeout=10)
        except Exception:
            # If we can't send the message, default to reject
            return False

        # Store message_id for later editing
        with kb_manager._lock:
            if conf_id in kb_manager._pending:
                kb_manager._pending[conf_id].message_id = sent_msg.message_id
                kb_manager._pending[conf_id].chat_id = chat_id

        # Schedule 5-minute async timeout that resolves as rejected
        async def _timeout():
            await asyncio.sleep(300)  # 5 minutes
            kb_manager.timeout_confirmation(conf_id)

        asyncio.run_coroutine_threadsafe(_timeout(), loop)

        # Wait for resolution (blocks the agent thread)
        try:
            result = future.result(timeout=310)  # slightly longer than async timeout
        except Exception:
            result = False

        return result

    return permission_callback


def _get_or_create_agent(chat_id: int, agent_factory: Callable, permission_cb=None):
    with _agents_lock:
        if chat_id not in _agents:
            agent = agent_factory(channel="telegram")
            agent.permission_callback = permission_cb
            # Restore persisted conversation history
            history = _load_tg_history(chat_id)
            if history:
                agent.messages.extend(history)
                logger.debug(f"Restored {len(history)} messages for chat_id={chat_id}")
            _agents[chat_id] = agent
        return _agents[chat_id]


async def _process_message(update, context, agent_factory: Callable,
                           kb_manager=None, bot_loop=None, override_text: str = ""):
    """Process one Telegram message: stream agent response back in real time."""
    import time as _time
    import queue as _queue
    from telegram.constants import ParseMode, ChatAction
    from telegram.error import BadRequest as _BadRequest

    msg = update.message or update.edited_message
    if not msg and not override_text:
        return

    chat_id = msg.chat_id if msg else update.callback_query.message.chat_id
    user_text = override_text or (msg.text if msg else "") or (msg.caption if msg else "") or ""
    image_path = None

    # Auto-save chat_id to config on first message (so proactive notifications work)
    if not override_text and chat_id:
        try:
            from config import load_config, save_config
            _cfg = load_config()
            _saved = _cfg.get("messaging", {}).get("telegram", {}).get("chat_id", "")
            if str(_saved) != str(chat_id):
                _cfg.setdefault("messaging", {}).setdefault("telegram", {})["chat_id"] = str(chat_id)
                save_config(_cfg)
        except Exception:
            pass

    if not override_text:
        # React with 👀 to acknowledge the message immediately
        try:
            from telegram import ReactionTypeEmoji
            await context.bot.set_message_reaction(
                chat_id=chat_id,
                message_id=msg.message_id,
                reaction=[ReactionTypeEmoji(emoji="👀")],
            )
        except Exception:
            pass  # Reactions not available in all chat types — ignore

    # ── Photo support ──────────────────────────────────────────────────────────
    if msg and msg.photo:
        photo = msg.photo[-1]
        tg_file = await context.bot.get_file(photo.file_id)
        import tempfile
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
        tmp.close()
        await tg_file.download_to_drive(tmp.name)
        image_path = tmp.name
        if not user_text:
            user_text = "Bu fotoğrafı analiz et."

    # ── Document / file support ────────────────────────────────────────────────
    elif msg and msg.document:
        doc = msg.document
        tg_file = await context.bot.get_file(doc.file_id)
        # Save to ~/.Koza/workspace/downloads/ so path survives and is accessible
        dl_dir = Path(_bot_cfg.get("workspace_path", Path.home() / ".Koza" / "workspace")) / "downloads"
        dl_dir.mkdir(parents=True, exist_ok=True)
        safe_name = re.sub(r"[^\w\.\-]", "_", doc.file_name or f"file_{doc.file_id[:8]}")
        dest = str(dl_dir / safe_name)
        await tg_file.download_to_drive(dest)
        file_info = f"[Dosya indirildi: {dest}]"
        mime = doc.mime_type or ""
        if user_text:
            user_text = f"{file_info}\n{user_text}"
        else:
            # Default: read text-based files, just acknowledge binary ones
            if any(mime.startswith(p) for p in ("text/", "application/json", "application/xml")) or dest.endswith((".py", ".txt", ".md", ".csv", ".yaml", ".yml", ".toml", ".log")):
                user_text = f"{file_info}\nBu dosyayı oku ve içeriğini özetle."
            elif dest.endswith(".pdf"):
                user_text = f"{file_info}\nBu PDF dosyası indirildi. Kullanıcı komut verince işleyeceğim."
            else:
                user_text = f"{file_info}\nDosya kaydedildi. Kullanıcı ne yapmamı istediğini söyleyecek."

    if not user_text:
        return

    # Get or create agent
    permission_cb = None
    if kb_manager and bot_loop:
        permission_cb = _make_permission_callback(
            chat_id, context.bot, bot_loop, kb_manager
        )
    agent = _get_or_create_agent(chat_id, agent_factory, permission_cb=permission_cb)

    if agent._busy:
        agent.interrupt()
        # Wait for the previous stream to finish (max 5s)
        for _ in range(50):
            if not agent._busy:
                break
            await asyncio.sleep(0.1)
        await context.bot.send_message(chat_id=chat_id, text="⏸ Previous task interrupted.")

    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    ev_queue: _queue.Queue = _queue.Queue()
    _DONE = object()

    def _stream_worker():
        try:
            # Pass image_path so vision-capable providers encode it as base64
            for event in agent.stream_chat(user_text, image_path=image_path):
                ev_queue.put(event)
        except Exception as e:
            ev_queue.put({"type": "error", "message": str(e)})
        finally:
            ev_queue.put(_DONE)

    threading.Thread(target=_stream_worker, daemon=True).start()

    # ── Single-message streaming with throttled edits ────────────────────────
    # Strategy: stream into one message; after each "turn" (tool_done or new
    # text following a tool cycle), start a FRESH message so the chat stays
    # readable and users aren't scrolling through a single edited wall.
    # Inline [CHOICE: A | B | C] patterns are auto-converted to buttons.

    text_buf    = ""       # accumulated response text for current message
    status      = ""       # ephemeral status line (tool activity)
    sent_msg    = None     # current Telegram message object
    last_edit   = 0.0      # timestamp of last edit
    edit_count  = 0        # edits on current message
    _MAX_EDITS  = 12       # after this many edits, next text starts a new msg

    _bg_task_ids: list[str] = []  # task IDs started in this turn (for watcher)

    async def _flush(force: bool = False):
        nonlocal sent_msg, last_edit, status, edit_count
        now = _time.time()
        if not force and (now - last_edit) < 1.5:
            return
        display = text_buf + (f"\n\n{status}" if status else "")
        display = _sanitize_response(_strip_markdown(display))
        if not display.strip():
            return
        # Overflow: start new message
        if len(display) > 4000:
            overflow = display[4000:]
            display  = display[:4000]
            try:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=sent_msg.message_id,
                    text=display,
                )
            except Exception:
                pass
            sent_msg = await context.bot.send_message(
                chat_id=chat_id, text=overflow[:4000],
            )
            edit_count = 0
            last_edit = now
            return
        if sent_msg is None:
            sent_msg = await context.bot.send_message(chat_id=chat_id, text=display)
            edit_count = 0
        else:
            try:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=sent_msg.message_id,
                    text=display,
                )
                edit_count += 1
            except _BadRequest:
                pass   # "message not modified" — ignore
            except Exception:
                sent_msg = await context.bot.send_message(chat_id=chat_id, text=display)
                edit_count = 0
        last_edit = now

    async def _finalize_msg_and_start_fresh(new_text: str = ""):
        """Lock current message (finalize) and start a new one."""
        nonlocal text_buf, sent_msg, edit_count, status
        status = ""
        await _flush(force=True)
        text_buf = new_text
        sent_msg = None
        edit_count = 0

    async def _send_choice_buttons(choices: list[str]) -> None:
        """Send inline keyboard for [CHOICE: A | B | C] patterns."""
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        buttons = [[InlineKeyboardButton(c.strip(), callback_data=f"choice::{c.strip()}")]
                   for c in choices if c.strip()]
        if not buttons:
            return
        await context.bot.send_message(
            chat_id=chat_id,
            text="Nasıl devam edelim?",
            reply_markup=InlineKeyboardMarkup(buttons),
        )

    import re as _re
    _CHOICE_RE = _re.compile(r"\[CHOICE:\s*([^\]]+)\]", _re.IGNORECASE)

    while True:
        try:
            event = ev_queue.get_nowait()
        except _queue.Empty:
            await _flush()
            await asyncio.sleep(0.05)
            continue

        if event is _DONE:
            break

        if not isinstance(event, dict):
            continue

        etype = event.get("type")

        if etype == "text":
            tok = event.get("token", "")
            text_buf += tok

            # Detect [CHOICE: A | B | C] in accumulated text
            choice_match = _CHOICE_RE.search(text_buf)
            if choice_match:
                # Remove the choice directive from text_buf
                before = text_buf[:choice_match.start()].strip()
                text_buf = before
                await _flush(force=True)
                options = choice_match.group(1).split("|")
                await _send_choice_buttons(options)
            else:
                await _flush()

        elif etype == "tool_start":
            name = event.get("name", "")
            status = f"⚙️ {name}…"
            # After enough edits on current message, start fresh for next block
            if edit_count >= _MAX_EDITS and text_buf.strip():
                await _finalize_msg_and_start_fresh()
            await _flush(force=True)

        elif etype == "tool_done":
            name = event.get("name", "")
            status = f"✅ {name}"
            await _flush(force=True)

            # Track background task IDs so we can register watchers
            if name == "spawn_subagent":
                result_str = str(event.get("result", ""))
                # spawn_subagent returns "Sub-agent {id} launched (background)..."
                m = _re.search(r"Sub-agent\s+([a-f0-9]{8})", result_str)
                if m:
                    _bg_task_ids.append(m.group(1))

            # New tool cycle starts fresh if current message is getting long
            if edit_count >= _MAX_EDITS:
                await _finalize_msg_and_start_fresh()

        elif etype == "interrupted":
            status = ""
            text_buf += "\n\n⏹ Kesildi."
            await _flush(force=True)
            return

        elif etype == "error":
            err = event.get('message', 'Hata')
            text_buf += f"\n\n❌ {err}"
            await _flush(force=True)
            return

    # Final flush: clear status, show clean response
    status = ""
    await _flush(force=True)

    # Persist conversation history for this chat_id (survives bot restart)
    try:
        _save_tg_history(chat_id, agent.messages)
    except Exception:
        pass

    # Register completion watchers for any background tasks started this turn
    for task_id in _bg_task_ids:
        _register_completion_watcher(task_id, chat_id, context.bot, bot_loop)

    # Change reaction to ✅ after response is complete
    try:
        from telegram import ReactionTypeEmoji
        await context.bot.set_message_reaction(
            chat_id=chat_id,
            message_id=msg.message_id,
            reaction=[ReactionTypeEmoji(emoji="✅")],
        )
    except Exception:
        pass


def start_bot_thread(agent_factory: Callable, cfg: dict) -> bool:
    """
    Start the Telegram bot in a dedicated daemon thread with its own event loop.
    agent_factory: callable() → Agent (called once per chat_id for isolation).
    Returns True on successful thread start.
    """
    global _bot_cfg
    _bot_cfg = cfg

    token = (
        cfg.get("telegram_token", "").strip()
        or cfg.get("messaging", {}).get("telegram", {}).get("token", "").strip()
    )
    if not token:
        return False

    def _bot_thread():
        # Each thread needs its own event loop for python-telegram-bot v20+
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        from telegram.ext import Application, MessageHandler, CallbackQueryHandler, filters
        from telegram.error import Conflict as _Conflict
        from bots.telegram_keyboards import InlineKeyboardManager
        from bots.telegram_notifier import ProactiveNotifier

        app = Application.builder().token(token).concurrent_updates(True).build()

        # ── Inline keyboard manager instance ─────────────────────────────────
        _kb_manager = InlineKeyboardManager()

        # ── ProactiveNotifier initialization via post_init hook ───────────────
        chat_id = cfg.get("messaging", {}).get("telegram", {}).get("chat_id", "")
        notifier = ProactiveNotifier.get_instance()

        async def _post_init(application):
            """Initialize ProactiveNotifier once the bot and loop are ready."""
            notifier.initialize(application.bot, loop, chat_id)
            notifier.schedule_daily_summary()

            # ── Send startup welcome if chat_id is configured ─────────────────
            if chat_id:
                try:
                    await application.bot.send_message(
                        chat_id=chat_id,
                        text=(
                            "🟢 *Koza bağlantısı kuruldu!*\n\n"
                            "Telegram üzerinden bana mesaj yazabilirsin. Hazırım! 🚀"
                        ),
                        parse_mode="Markdown",
                    )
                except Exception:
                    pass  # chat_id geçersiz veya bot henüz başlatılmamış olabilir

            # ── Sub-agent completion notifications via SubAgentNotifier ──────
            _tg_loop = loop
            _tg_bot  = application.bot
            _tg_chat = chat_id

            def _tg_subagent_notify(agent_id: str, status: str, goal: str, result: str) -> None:
                if not _tg_chat:
                    return
                icon = "✅" if status == "done" else "❌"
                text = (
                    f"{icon} *Alt-agent tamamlandı* `{agent_id}`\n"
                    f"📋 Görev: {goal}\n"
                    f"💬 Özet: {result[:300] or '(sonuç yok)'}"
                )
                asyncio.run_coroutine_threadsafe(
                    _tg_bot.send_message(chat_id=_tg_chat, text=text, parse_mode="Markdown"),
                    _tg_loop,
                )

            try:
                from skills.agents.notifier import SubAgentNotifier
                SubAgentNotifier.register(_tg_subagent_notify)
                SubAgentNotifier.start()
            except Exception:
                pass

        app.post_init = _post_init

        # ── Callback query handler for inline buttons ────────────────────────
        async def on_callback_query(update, context):
            """Route inline button presses to the appropriate handler."""
            query = update.callback_query
            await query.answer()  # Acknowledge the callback

            data = query.data  # e.g. "tool:a1b2c3d4:approve"
            if not data:
                return

            parts = data.split(":", 2)

            # Handle choice buttons (format: "choice::{selected_option}")
            if data.startswith("choice::"):
                selected = data[len("choice::"):]
                await query.edit_message_reply_markup(reply_markup=None)
                await query.message.reply_text(f"✅ {selected}")
                await _process_message(
                    update, context, agent_factory,
                    kb_manager=_kb_manager, bot_loop=loop,
                    override_text=selected,
                )
                return

            if len(parts) != 3:
                return

            action_type, identifier, payload = parts

            if action_type == "tool":
                await _handle_tool_callback(query, identifier, payload, _kb_manager)
            elif action_type == "task":
                await _handle_task_callback(query, identifier, payload)

        async def _handle_tool_callback(query, conf_id: str, action: str, kb_manager):
            """Handle tool approve/reject button press."""
            approved = action == "approve"
            pending = kb_manager.resolve_confirmation(conf_id, approved)

            if pending is None:
                await query.edit_message_text("⏰ This confirmation has expired.")
                return

            if approved:
                await query.edit_message_text(
                    f"✅ Approved: `{pending.tool_name}`", parse_mode="Markdown"
                )
            else:
                await query.edit_message_text(
                    f"❌ Rejected: `{pending.tool_name}`", parse_mode="Markdown"
                )

        async def _handle_task_callback(query, task_id: str, action: str):
            """Handle background task status/cancel button press."""
            status = BackgroundTaskManager.get_status(task_id)

            # Task not found — handle for both actions
            if not status:
                await query.edit_message_reply_markup(reply_markup=None)
                await query.message.reply_text(
                    f"⚠️ Task `{task_id}` not found.", parse_mode="Markdown"
                )
                return

            # If task is in terminal state, remove keyboard and inform user
            if status["status"] in ("done", "error", "cancelled"):
                await query.edit_message_reply_markup(reply_markup=None)
                await query.message.reply_text(
                    f"Task `{task_id}` is already {status['status']}.",
                    parse_mode="Markdown",
                )
                return

            if action == "status":
                elapsed = status.get("elapsed_seconds", 0)
                persona = status.get("current_persona") or "initializing"
                completed = status.get("completed_subtasks", 0)
                total = status.get("total_subtasks", 0)
                text = (
                    f"📊 **Task {task_id}**\n"
                    f"⏱ Elapsed: {elapsed:.0f}s\n"
                    f"🎭 Current: {persona}\n"
                    f"📋 Progress: {completed}/{total} subtasks"
                )
                await query.message.reply_text(text, parse_mode="Markdown")

            elif action == "cancel":
                success = BackgroundTaskManager.cancel_task(task_id)
                if success:
                    await query.edit_message_reply_markup(reply_markup=None)
                    await query.edit_message_text(
                        f"🛑 Task `{task_id}` cancelled.", parse_mode="Markdown"
                    )
                else:
                    await query.message.reply_text(
                        f"⚠️ Cannot cancel task `{task_id}` — not in a running state.",
                        parse_mode="Markdown",
                    )

        async def on_message(update, context):
            try:
                await _process_message(
                    update, context, agent_factory,
                    kb_manager=_kb_manager, bot_loop=loop,
                )
            except Exception as e:
                logger.error(f"Telegram handler error: {e}", exc_info=True)
                try:
                    chat_id = (update.message or update.edited_message).chat_id
                    await context.bot.send_message(chat_id=chat_id, text=f"❌ Hata: {e}")
                except Exception:
                    pass

        async def on_error(update, context):
            """Handle errors silently — especially Conflict errors."""
            if isinstance(context.error, _Conflict):
                logger.warning("Telegram Conflict: another bot instance is running. Stopping this one.")
                # Don't crash — just log and let polling retry handle it
                return
            logger.error(f"Telegram error: {context.error}", exc_info=context.error)

        app.add_handler(MessageHandler(
            (filters.TEXT | filters.PHOTO | filters.DOCUMENT | filters.CAPTION) & ~filters.COMMAND,
            on_message,
        ))
        app.add_handler(CallbackQueryHandler(on_callback_query))
        app.add_error_handler(on_error)

        # ── /start command: save chat_id and send welcome ─────────────────────
        from telegram.ext import CommandHandler as _CmdHandler

        async def on_start(update, context):
            cid = update.effective_chat.id
            uname = update.effective_user.username or update.effective_user.first_name or str(cid)
            # Persist chat_id to config so future startups can message proactively
            try:
                from config import load_config, save_config
                c = load_config()
                c.setdefault("messaging", {}).setdefault("telegram", {})["chat_id"] = str(cid)
                save_config(c)
            except Exception:
                pass
            await update.message.reply_text(
                f"👋 Merhaba @{uname}!\n\n"
                "Ben *Koza*, senin yapay zeka asistanın. Telegram bağlantımız başarıyla kuruldu! 🎉\n\n"
                "Artık buradan bana istediğini yazabilirsin. Sana nasıl yardımcı olabilirim?",
                parse_mode="Markdown",
            )

        app.add_handler(_CmdHandler("start", on_start))

        # ── /version command ──────────────────────────────────────────────────
        async def on_version(update, context):
            from cli.ui._banner import _get_version
            import urllib.request, json, re
            current = _get_version()
            latest = ""
            try:
                req = urllib.request.Request(
                    "https://api.github.com/repos/haydarkadioglu/koza-agent/releases/latest",
                    headers={"User-Agent": "koza-agent"},
                )
                with urllib.request.urlopen(req, timeout=5) as r:
                    tag = json.loads(r.read()).get("tag_name", "").lstrip("v")
                    if tag:
                        latest = tag
            except Exception:
                pass
            if not latest:
                try:
                    req2 = urllib.request.Request(
                        "https://raw.githubusercontent.com/haydarkadioglu/koza-agent/main/pyproject.toml",
                        headers={"User-Agent": "koza-agent"},
                    )
                    with urllib.request.urlopen(req2, timeout=5) as r:
                        m = re.search(r'^version\s*=\s*"([^"]+)"', r.read().decode(), re.MULTILINE)
                        if m:
                            latest = m.group(1)
                except Exception:
                    pass

            lines = [f"🐛 *Koza* `v{current}`"]
            if latest:
                try:
                    from packaging.version import Version
                    if Version(latest) > Version(current):
                        lines.append(f"🆕 Update available: `v{latest}`\nRun `koza update` to upgrade.")
                    else:
                        lines.append("✅ You're on the latest version.")
                except Exception:
                    lines.append(f"Latest on GitHub: `v{latest}`")
            await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

        app.add_handler(_CmdHandler("version", on_version))

        try:
            app.run_polling(
                allowed_updates=["message", "edited_message", "callback_query"],
                drop_pending_updates=True,
                close_loop=False,
            )
        except _Conflict:
            logger.warning("Telegram bot stopped: another instance is already running.")
        except Exception as e:
            logger.error(f"Telegram bot crashed: {e}", exc_info=True)
        finally:
            loop.close()

    t = threading.Thread(target=_bot_thread, daemon=True, name="telegram-bot")
    t.start()
    logger.info("Telegram bot thread started.")
    return True

