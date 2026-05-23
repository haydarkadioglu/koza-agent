"""
Proactive Telegram notifier for Koza.

Sends scheduled/proactive messages (daily summaries, cron completion alerts,
reminders) to the configured Telegram chat. Bridges APScheduler threads to
the Telegram bot's async event loop via asyncio.run_coroutine_threadsafe.
"""
import asyncio
import logging
import threading
import uuid
from collections import deque
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# Retry constants
MAX_RETRIES = 3
INITIAL_BACKOFF_SECONDS = 5


class ProactiveNotifier:
    """
    Sends scheduled/proactive messages to the configured Telegram chat.
    Bridges APScheduler threads → Telegram bot's async event loop.
    """

    _instance: Optional["ProactiveNotifier"] = None

    def __init__(self):
        self._bot = None  # telegram.Bot instance
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._chat_id: str = ""
        self._message_queue: deque = deque(maxlen=100)
        self._lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> "ProactiveNotifier":
        """Return the singleton instance, creating it if necessary."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def initialize(self, bot, loop: asyncio.AbstractEventLoop, chat_id: str):
        """
        Called once when the Telegram bot thread starts.
        Sets bot reference, event loop, chat_id, and flushes queued messages.
        """
        self._bot = bot
        self._loop = loop
        self._chat_id = chat_id
        # Flush any queued messages now that the loop is available
        self._flush_queue()

    def send_message(self, text: str) -> bool:
        """
        Send a proactive message to the configured chat_id.
        Thread-safe — can be called from APScheduler threads.
        Returns True if dispatch succeeded.
        """
        if not self._chat_id:
            logger.warning("ProactiveNotifier: chat_id not configured, skipping.")
            return False

        if not self._loop or not self._loop.is_running():
            # Queue for later delivery
            with self._lock:
                self._message_queue.append(text)
            logger.warning("ProactiveNotifier: event loop not running, message queued.")
            return False

        asyncio.run_coroutine_threadsafe(
            self._send_with_retry(text), self._loop
        )
        return True

    async def _send_with_retry(self, text: str):
        """Send message with exponential backoff retry on failure."""
        backoff = INITIAL_BACKOFF_SECONDS
        for attempt in range(MAX_RETRIES + 1):
            try:
                await self._bot.send_message(
                    chat_id=int(self._chat_id), text=text, parse_mode="Markdown"
                )
                return
            except Exception as e:
                if attempt == MAX_RETRIES:
                    logger.error(f"ProactiveNotifier: failed after {MAX_RETRIES} retries: {e}")
                    return
                logger.warning(
                    f"ProactiveNotifier: send failed (attempt {attempt + 1}), "
                    f"retrying in {backoff}s: {e}"
                )
                await asyncio.sleep(backoff)
                backoff *= 2

    def _flush_queue(self):
        """Send any queued messages now that the loop is available."""
        with self._lock:
            while self._message_queue:
                text = self._message_queue.popleft()
                if self._loop and self._loop.is_running():
                    asyncio.run_coroutine_threadsafe(
                        self._send_with_retry(text), self._loop
                    )

    # ── Reminders ────────────────────────────────────────────────────────

    def schedule_reminder(self, text: str, remind_at: datetime) -> str:
        """
        Schedule a one-time reminder.
        Returns confirmation message or error string.
        """
        from apscheduler.triggers.date import DateTrigger
        from skills.cron_scheduler import get_scheduler

        now = datetime.now()
        if remind_at <= now:
            return "Error: reminder time is in the past."

        reminder_id = uuid.uuid4().hex[:8]
        scheduler = get_scheduler()
        scheduler.add_job(
            self._reminder_job,
            DateTrigger(run_date=remind_at),
            args=[text],
            id=f"koza_reminder_{reminder_id}",
            name=f"Reminder: {text[:30]}",
        )
        return f"Reminder scheduled for {remind_at.strftime('%Y-%m-%d %H:%M')} (id: {reminder_id})"

    def _reminder_job(self, text: str):
        """APScheduler callback for a reminder — runs in scheduler thread."""
        self.send_message(f"🔔 **Reminder:** {text}")

    # ── Daily Summary ────────────────────────────────────────────────────

    def schedule_daily_summary(self, hour: int = 9, minute: int = 0):
        """Register the daily summary job with APScheduler."""
        from apscheduler.triggers.cron import CronTrigger
        from skills.cron_scheduler import get_scheduler

        scheduler = get_scheduler()
        scheduler.add_job(
            self._daily_summary_job,
            CronTrigger(hour=hour, minute=minute),
            id="koza_daily_summary",
            replace_existing=True,
        )
        logger.info(f"Daily summary scheduled at {hour:02d}:{minute:02d}")

    def _daily_summary_job(self):
        """APScheduler callback — runs in scheduler thread. Gathers data and sends summary."""
        from skills.agents.background import BackgroundTaskManager
        from skills.cron_scheduler import get_scheduler as _get_sched

        # Gather pending/running background tasks
        tasks = BackgroundTaskManager.list_tasks()
        pending = [t for t in tasks if t["status"] in ("pending", "running")]

        # Gather today's cron jobs (exclude internal jobs)
        scheduler = _get_sched()
        today_jobs = []
        now = datetime.now()
        for job in scheduler.get_jobs():
            if job.id.startswith("koza_reminder_") or job.id == "koza_daily_summary":
                continue
            next_run = job.next_run_time
            if next_run and next_run.date() == now.date():
                today_jobs.append(job.name or job.id)

        # Gather active reminders
        reminders = [
            j.name or j.id
            for j in scheduler.get_jobs()
            if j.id.startswith("koza_reminder_")
        ]

        # Format summary message
        lines = ["☀️ **Daily Summary**\n"]
        lines.append(f"📋 Pending tasks: {len(pending)}")
        if today_jobs:
            lines.append(f"⏰ Today's cron jobs: {', '.join(today_jobs)}")
        else:
            lines.append("⏰ No cron jobs scheduled for today")
        if reminders:
            lines.append(f"🔔 Active reminders: {len(reminders)}")

        self.send_message("\n".join(lines))

    # ── Cron Completion Hook ─────────────────────────────────────────────

    def notify_cron_completion(self, job_name: str, success: bool, error: Optional[str] = None):
        """
        Called after a cron job finishes. Sends a completion notification.

        Args:
            job_name: Name of the cron job that completed.
            success: True if the job completed successfully, False otherwise.
            error: Error description if the job failed (optional).
        """
        if success:
            text = f"✅ Cron job `{job_name}` completed successfully."
        else:
            text = f"❌ Cron job `{job_name}` failed: {error or 'Unknown error'}"
        self.send_message(text)
