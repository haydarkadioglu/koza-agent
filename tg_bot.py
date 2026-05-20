"""
Koza Telegram Bot
- Arka planda thread olarak çalışır, aynı Agent örneğini kullanır
- İlk mesajı atan kullanıcı otomatik olarak owner olur (config'e kaydedilir)
- Sonraki açılışlarda token varsa otomatik başlar
"""
import asyncio
import html
import logging
import re
import threading
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, MessageHandler, CommandHandler, CallbackQueryHandler, ContextTypes, filters
from telegram.constants import ChatAction, ParseMode

logging.basicConfig(level=logging.WARNING)

_bot_thread: Optional[threading.Thread] = None
_app: Optional[Application] = None

# Quick-action keyboard shown persistently at the bottom
_QUICK_KEYBOARD = ReplyKeyboardMarkup(
    [[KeyboardButton("📂 Dosyalar"), KeyboardButton("🖥 Sistem"), KeyboardButton("❓ Yardım")],
     [KeyboardButton("🧠 Hafıza"), KeyboardButton("📋 Son görevler"), KeyboardButton("⚙ Durum")]],
    resize_keyboard=True,
    one_time_keyboard=False,
)

# Maps quick-button labels to actual prompts sent to agent
_QUICK_MAP = {
    "📂 Dosyalar": "Masaüstündeki ve İndirilenler klasöründeki dosyaları listele.",
    "🖥 Sistem": "Sistemin durumunu özetle: CPU, RAM, disk kullanımı.",
    "❓ Yardım": "Neler yapabilirsin? Kısa bir özet ver.",
    "🧠 Hafıza": "Çalışma hafızamda ne var? Özetle.",
    "📋 Son görevler": "Son yaptığın görevleri listele.",
    "⚙ Durum": "Koza agent durumunu ve aktif servisleri göster.",
}


def _md_to_html(text: str) -> str:
    """Convert Markdown-style text from LLM to Telegram HTML."""
    # Escape HTML entities first
    text = html.escape(text)

    # Code blocks (``` ... ```) → <pre><code>
    text = re.sub(r"```(?:\w+)?\n?(.*?)```", lambda m: f"<pre><code>{m.group(1).strip()}</code></pre>", text, flags=re.DOTALL)

    # Inline code
    text = re.sub(r"`([^`\n]+)`", r"<code>\1</code>", text)

    # Bold **text** or __text__
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"__(.+?)__", r"<b>\1</b>", text)

    # Italic *text* or _text_  (skip if already inside a tag)
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<i>\1</i>", text)
    text = re.sub(r"(?<!_)_(?!_)(.+?)(?<!_)_(?!_)", r"<i>\1</i>", text)

    # Convert markdown table rows  | A | B | C |  →  simple line
    def _table_row(m):
        cells = [c.strip() for c in m.group(0).split("|") if c.strip()]
        return "  ".join(cells)

    text = re.sub(r"^\|.+\|$", _table_row, text, flags=re.MULTILINE)
    # Remove table separator lines (|---|---|)
    text = re.sub(r"^\|[-| :]+\|$", "", text, flags=re.MULTILINE)

    # Remove leftover lone pipe chars
    text = re.sub(r" \| ", "  •  ", text)

    # Clean up excessive blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def _make_inline_kb(buttons: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    """Build a single-row inline keyboard from (label, callback_data) pairs."""
    return InlineKeyboardMarkup([[InlineKeyboardButton(label, callback_data=data) for label, data in buttons]])


def _save_owner(chat_id: int):
    """Save first-message sender as the only allowed chat_id."""
    try:
        from config import load_config, save_config
        c = load_config()
        c["telegram_owner_id"] = chat_id
        save_config(c)
    except Exception:
        pass


async def _stream_reply(agent, user_text: str, update: Update, context: ContextTypes.DEFAULT_TYPE = None):
    """Run agent.stream_chat (sync generator) in a thread and send formatted reply."""
    chat_id = update.effective_chat.id
    bot = update.get_bot()
    await bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    full = ""
    tool_log = []

    loop = asyncio.get_event_loop()

    def _collect():
        nonlocal full, tool_log
        for event in agent.stream_chat(user_text):
            if not isinstance(event, dict):
                continue
            etype = event.get("type")
            if etype == "text":
                full += event.get("token", "")
            elif etype == "tool_start":
                tool_log.append(f"⚙️ <code>{html.escape(event['name'])}</code>")
            elif etype == "tool_done":
                elapsed = event.get("elapsed", 0)
                if tool_log:
                    tool_log[-1] += f" ✓ {elapsed:.1f}s"

    await loop.run_in_executor(None, _collect)

    # Build tool activity header
    header = ""
    if tool_log:
        header = "\n".join(tool_log) + "\n\n"

    body = _md_to_html(full) if full.strip() else "<i>(yanıt yok)</i>"
    reply = header + body

    # Send in chunks (Telegram 4096 char limit)
    chunks = [reply[i:i + 4000] for i in range(0, len(reply), 4000)]
    for idx, chunk in enumerate(chunks):
        is_last = idx == len(chunks) - 1
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=chunk,
                parse_mode=ParseMode.HTML,
                reply_markup=_QUICK_KEYBOARD if is_last else None,
            )
        except Exception:
            # Fallback: send as plain text if HTML parsing fails
            plain = re.sub(r"<[^>]+>", "", chunk)
            await bot.send_message(chat_id=chat_id, text=plain, reply_markup=_QUICK_KEYBOARD if is_last else None)


async def _on_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cfg = context.bot_data["cfg"]
    owner_id = cfg.get("telegram_owner_id")
    sender_id = update.effective_user.id

    if not owner_id:
        _save_owner(sender_id)
        context.bot_data["cfg"]["telegram_owner_id"] = sender_id
        await update.message.reply_text(
            "👋 <b>Koza Agent aktif!</b>\n"
            "Sen artık bu botun sahibisin. Soru sorabilirsin.",
            parse_mode=ParseMode.HTML,
            reply_markup=_QUICK_KEYBOARD,
        )
    elif sender_id == owner_id:
        await update.message.reply_text(
            "👋 <b>Koza Agent hazır.</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=_QUICK_KEYBOARD,
        )
    else:
        await update.message.reply_text("⛔ Bu bot özel kullanım içindir.")


async def _on_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cfg = context.bot_data["cfg"]
    owner_id = cfg.get("telegram_owner_id")
    sender_id = update.effective_user.id

    if not owner_id:
        _save_owner(sender_id)
        context.bot_data["cfg"]["telegram_owner_id"] = sender_id
        owner_id = sender_id

    if sender_id != owner_id:
        await update.message.reply_text("⛔ Yetkisiz kullanıcı.")
        return

    user_text = update.message.text
    # Remap quick keyboard labels to full prompts
    user_text = _QUICK_MAP.get(user_text, user_text)

    agent = context.bot_data["agent"]
    await _stream_reply(agent, user_text, update, context)


async def _on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline keyboard button presses."""
    query = update.callback_query
    await query.answer()

    cfg = context.bot_data["cfg"]
    owner_id = cfg.get("telegram_owner_id")
    if query.from_user.id != owner_id:
        return

    # Treat callback data as a new message prompt
    data = query.data
    prompt = _QUICK_MAP.get(data, data)
    agent = context.bot_data["agent"]

    # Fake update object reuse — send via bot directly
    chat_id = query.message.chat_id
    bot = query.get_bot()
    await bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    full = ""
    tool_log = []
    loop = asyncio.get_event_loop()

    def _collect():
        nonlocal full, tool_log
        for event in agent.stream_chat(prompt):
            if not isinstance(event, dict):
                continue
            etype = event.get("type")
            if etype == "text":
                full += event.get("token", "")
            elif etype == "tool_start":
                tool_log.append(f"⚙️ <code>{html.escape(event['name'])}</code>")
            elif etype == "tool_done":
                elapsed = event.get("elapsed", 0)
                if tool_log:
                    tool_log[-1] += f" ✓ {elapsed:.1f}s"

    await loop.run_in_executor(None, _collect)

    header = ("\n".join(tool_log) + "\n\n") if tool_log else ""
    body = _md_to_html(full) if full.strip() else "<i>(yanıt yok)</i>"
    reply = header + body

    chunks = [reply[i:i + 4000] for i in range(0, len(reply), 4000)]
    for idx, chunk in enumerate(chunks):
        is_last = idx == len(chunks) - 1
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=chunk,
                parse_mode=ParseMode.HTML,
                reply_markup=_QUICK_KEYBOARD if is_last else None,
            )
        except Exception:
            plain = re.sub(r"<[^>]+>", "", chunk)
            await bot.send_message(chat_id=chat_id, text=plain, reply_markup=_QUICK_KEYBOARD if is_last else None)


def start_bot_thread(agent, cfg: dict) -> bool:
    """
    Start the Telegram bot in a background daemon thread.
    Returns True if started, False if no token configured.
    """
    global _bot_thread, _app

    token = (
        cfg.get("telegram_token", "").strip()
        or cfg.get("messaging", {}).get("telegram", {}).get("token", "").strip()
    )
    if not token:
        return False

    if _bot_thread and _bot_thread.is_alive():
        return True  # already running

    def _run():
        global _app
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        app = Application.builder().token(token).build()
        app.bot_data["agent"] = agent
        app.bot_data["cfg"] = cfg

        app.add_handler(CommandHandler("start", _on_start))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _on_message))
        app.add_handler(CallbackQueryHandler(_on_callback))

        _app = app
        app.run_polling(drop_pending_updates=True, stop_signals=None)

    _bot_thread = threading.Thread(target=_run, daemon=True, name="koza-telegram")
    _bot_thread.start()
    return True


def run_bot_foreground(token: str, cfg: dict, agent=None):
    """Run bot in foreground (blocking). Used by `koza telegram` command."""
    if agent is None:
        from config import load_config
        from providers.factory import get_provider
        from core import Agent
        cfg = load_config()
        agent = Agent(get_provider(cfg), db_path=cfg["db_path"], cfg=cfg)
        agent.permission_callback = None

    app = Application.builder().token(token).build()
    app.bot_data["agent"] = agent
    app.bot_data["cfg"] = cfg

    app.add_handler(CommandHandler("start", _on_start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _on_message))
    app.add_handler(CallbackQueryHandler(_on_callback))

    print(f"  🤖  Koza Telegram Bot dinleniyor. Durdurmak için Ctrl+C\n")
    app.run_polling(drop_pending_updates=True)

