"""Email skill — SMTP send, IMAP read, search, reply."""
import smtplib
import imaplib
import email as _email
import ssl as _ssl
import csv
import os
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.application import MIMEApplication
from email import encoders as _encoders
from email.header import decode_header as _decode_header
from email.utils import formataddr as _formataddr, parseaddr as _parseaddr
from pathlib import Path
from typing import Optional

# ── Auto-detect SMTP/IMAP settings from email domain ────────────────────────
_DOMAIN_PRESETS = {
    "gmail.com":       {"smtp_host": "smtp.gmail.com",          "smtp_port": 587, "imap_host": "imap.gmail.com"},
    "googlemail.com":  {"smtp_host": "smtp.gmail.com",          "smtp_port": 587, "imap_host": "imap.gmail.com"},
    "outlook.com":     {"smtp_host": "smtp.office365.com",      "smtp_port": 587, "imap_host": "outlook.office365.com"},
    "hotmail.com":     {"smtp_host": "smtp.office365.com",      "smtp_port": 587, "imap_host": "outlook.office365.com"},
    "live.com":        {"smtp_host": "smtp.office365.com",      "smtp_port": 587, "imap_host": "outlook.office365.com"},
    "yahoo.com":       {"smtp_host": "smtp.mail.yahoo.com",     "smtp_port": 587, "imap_host": "imap.mail.yahoo.com"},
    "ymail.com":       {"smtp_host": "smtp.mail.yahoo.com",     "smtp_port": 587, "imap_host": "imap.mail.yahoo.com"},
    "icloud.com":      {"smtp_host": "smtp.mail.me.com",        "smtp_port": 587, "imap_host": "imap.mail.me.com"},
    "me.com":          {"smtp_host": "smtp.mail.me.com",        "smtp_port": 587, "imap_host": "imap.mail.me.com"},
    "protonmail.com":  {"smtp_host": "smtp.protonmail.ch",      "smtp_port": 587, "imap_host": "imap.protonmail.ch"},
    "proton.me":       {"smtp_host": "smtp.protonmail.ch",      "smtp_port": 587, "imap_host": "imap.protonmail.ch"},
    "yandex.com":      {"smtp_host": "smtp.yandex.com",         "smtp_port": 587, "imap_host": "imap.yandex.com"},
    "yandex.ru":       {"smtp_host": "smtp.yandex.ru",          "smtp_port": 587, "imap_host": "imap.yandex.ru"},
    "zoho.com":        {"smtp_host": "smtp.zoho.com",           "smtp_port": 587, "imap_host": "imap.zoho.com"},
    "fastmail.com":    {"smtp_host": "smtp.fastmail.com",       "smtp_port": 587, "imap_host": "imap.fastmail.com"},
}


def _preset_for(email_addr: str) -> dict:
    """Return SMTP/IMAP preset dict for email domain, or empty dict."""
    domain = email_addr.lower().split("@")[-1] if "@" in email_addr else ""
    return _DOMAIN_PRESETS.get(domain, {})


def _decode_str(s: str) -> str:
    """Decode RFC 2047 encoded email header string."""
    if not s:
        return ""
    parts = []
    for chunk, enc in _decode_header(s):
        if isinstance(chunk, bytes):
            parts.append(chunk.decode(enc or "utf-8", errors="replace"))
        else:
            parts.append(chunk)
    return "".join(parts)


def _parse_recipients(recipients) -> list[str]:
    """Accept str (comma-sep) or list → list of addresses."""
    if isinstance(recipients, list):
        return [r.strip() for r in recipients if r.strip()]
    return [r.strip() for r in str(recipients).split(",") if r.strip()]


TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "send_email",
            "description": (
                "Send an email via SMTP. Supports HTML body, CC/BCC, file attachments, "
                "and multiple recipients. SMTP settings are auto-detected from the email domain "
                "(gmail, outlook, yahoo, icloud, etc.) when not specified."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {
                        "type": "string",
                        "description": "Recipient(s) — comma-separated addresses or single address.",
                    },
                    "subject": {"type": "string", "description": "Email subject line."},
                    "body": {
                        "type": "string",
                        "description": "Email body. Plain text by default; set html=true for HTML content.",
                    },
                    "html": {
                        "type": "boolean",
                        "default": False,
                        "description": "Set true to send body as HTML instead of plain text.",
                    },
                    "cc": {
                        "type": "string",
                        "description": "CC recipient(s), comma-separated. Optional.",
                    },
                    "bcc": {
                        "type": "string",
                        "description": "BCC recipient(s), comma-separated. Optional.",
                    },
                    "sender_name": {
                        "type": "string",
                        "description": "Display name for the sender (e.g. 'Koza Agent'). Optional.",
                    },
                    "reply_to": {
                        "type": "string",
                        "description": "Reply-To address. Optional.",
                    },
                    "attachments": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of absolute file paths to attach to the email. Optional.",
                    },
                    "smtp_host": {
                        "type": "string",
                        "description": "SMTP server host. Auto-detected from sender email domain if omitted.",
                    },
                    "smtp_port": {
                        "type": "integer",
                        "description": "SMTP port. Use 587 (STARTTLS, default) or 465 (SSL). Auto-detected if omitted.",
                    },
                    "username": {
                        "type": "string",
                        "description": "SMTP username / sender email. Uses config value if omitted.",
                    },
                    "password": {
                        "type": "string",
                        "description": "SMTP password or app password. Uses config value if omitted.",
                    },
                },
                "required": ["to", "subject", "body"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_emails",
            "description": (
                "Read emails from an IMAP mailbox. Supports folder selection, "
                "unread filter, and returns full decoded email content."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "folder": {
                        "type": "string",
                        "default": "INBOX",
                        "description": "Mailbox folder to read from (e.g. INBOX, Sent, Drafts).",
                    },
                    "limit": {
                        "type": "integer",
                        "default": 5,
                        "description": "Number of most recent emails to return (max 20).",
                    },
                    "unread_only": {
                        "type": "boolean",
                        "default": False,
                        "description": "If true, return only unread emails.",
                    },
                    "mark_as_read": {
                        "type": "boolean",
                        "default": False,
                        "description": "If true, mark fetched emails as read.",
                    },
                    "imap_host": {
                        "type": "string",
                        "description": "IMAP server host. Auto-detected from username domain if omitted.",
                    },
                    "username": {
                        "type": "string",
                        "description": "IMAP username / email address. Uses config value if omitted.",
                    },
                    "password": {
                        "type": "string",
                        "description": "IMAP password or app password. Uses config value if omitted.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_emails",
            "description": (
                "Search emails in a mailbox using IMAP criteria. "
                "Can search by sender, subject, body text, or date range."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "Free-text search query. Searches subject and sender. "
                            "Examples: 'fatura', 'from:boss@company.com', 'subject:meeting'"
                        ),
                    },
                    "folder": {"type": "string", "default": "INBOX"},
                    "limit": {"type": "integer", "default": 10},
                    "since_date": {
                        "type": "string",
                        "description": "Only return emails after this date (format: DD-Mon-YYYY, e.g. '01-May-2025').",
                    },
                    "imap_host": {"type": "string"},
                    "username": {"type": "string"},
                    "password": {"type": "string"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "reply_email",
            "description": "Reply to an existing email, preserving the thread (In-Reply-To header).",
            "parameters": {
                "type": "object",
                "properties": {
                    "message_id": {
                        "type": "string",
                        "description": "The Message-ID header value of the email to reply to.",
                    },
                    "reply_body": {
                        "type": "string",
                        "description": "The reply text.",
                    },
                    "html": {"type": "boolean", "default": False},
                    "reply_to_sender": {
                        "type": "string",
                        "description": "Recipient address (sender of original email).",
                    },
                    "subject": {
                        "type": "string",
                        "description": "Subject override. If omitted, 'Re: <original subject>' is used.",
                    },
                    "smtp_host": {"type": "string"},
                    "smtp_port": {"type": "integer"},
                    "username": {"type": "string"},
                    "password": {"type": "string"},
                },
                "required": ["message_id", "reply_body", "reply_to_sender"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_batch_emails",
            "description": (
                "Send the same email to multiple recipients in batch. "
                "Supports personalization with {name} placeholder in subject/body. "
                "Each recipient gets an individual email (not CC/BCC). "
                "Automatically logs all sent emails to ~/.Koza/email_log.csv"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "recipients": {
                        "type": "array",
                        "description": (
                            "List of recipients. Simple list: ['a@x.com', 'b@x.com']. "
                            "For personalization: [{'to': 'a@x.com', 'name': 'Ali'}, ...]"
                        ),
                        "items": {},
                    },
                    "subject": {"type": "string", "description": "Email subject. Use {name} for personalization."},
                    "body": {"type": "string", "description": "Email body. Use {name} for personalization."},
                    "html": {"type": "boolean", "default": False},
                    "personalized": {"type": "boolean", "default": False, "description": "Set true if recipients is list of {to, name} dicts."},
                    "sender_name": {"type": "string", "default": ""},
                    "attachments": {"type": "array", "items": {"type": "string"}, "default": []},
                },
                "required": ["recipients", "subject", "body"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "email_log",
            "description": "Show recent sent email log from ~/.Koza/email_log.csv.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "default": 20, "description": "How many recent entries to show."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "email_setup",
            "description": "Interactive email setup wizard. Configures SMTP/IMAP credentials and saves to Koza config. Walks through App Password setup for Gmail.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]

_email_cfg: dict = {}


def init_email(cfg: dict):
    global _email_cfg
    _email_cfg = cfg.get("email", {})


def _resolve_credentials(
    username: str = "",
    password: str = "",
    smtp_host: str = "",
    smtp_port: int = 0,
    imap_host: str = "",
) -> tuple[str, str, str, int, str]:
    """Resolve email credentials with multiple fallbacks (config, env, shared_memory)."""
    from config import load_config
    try:
        cfg = load_config()
        email_cfg = cfg.get("email", {})
    except Exception:
        email_cfg = _email_cfg

    u = username or email_cfg.get("username", "")
    p = password or email_cfg.get("password", "")

    # 1. Fallback to OS Environment Variables
    if not u:
        u = os.getenv("EMAIL_USERNAME", "")
    if not p:
        p = os.getenv("EMAIL_PASSWORD", "")

    # 2. Fallback to shared_memory credential pool (.env)
    if not u or not p:
        try:
            from skills import shared_memory
            env_data = shared_memory._read_env()
            if not u and "EMAIL_USERNAME" in env_data:
                u = env_data["EMAIL_USERNAME"][0]
            if not p and "EMAIL_PASSWORD" in env_data:
                p = env_data["EMAIL_PASSWORD"][0]
        except Exception:
            pass

    # Resolve SMTP/IMAP settings using preset or fallback configurations
    preset = _preset_for(u)

    h_smtp = smtp_host or email_cfg.get("smtp_host", "") or preset.get("smtp_host", "smtp.gmail.com")
    port_smtp = smtp_port or email_cfg.get("smtp_port", 0) or preset.get("smtp_port", 587)

    # Check if host or port settings exist in env or shared_memory
    if not smtp_host:
        h_smtp_env = os.getenv("SMTP_HOST", "")
        if h_smtp_env:
            h_smtp = h_smtp_env
        else:
            try:
                from skills import shared_memory
                env_data = shared_memory._read_env()
                if "SMTP_HOST" in env_data:
                    h_smtp = env_data["SMTP_HOST"][0]
            except Exception:
                pass

    if not smtp_port or smtp_port == 0:
        port_smtp_env = os.getenv("SMTP_PORT", "")
        if port_smtp_env.isdigit():
            port_smtp = int(port_smtp_env)
        else:
            try:
                from skills import shared_memory
                env_data = shared_memory._read_env()
                if "SMTP_PORT" in env_data and env_data["SMTP_PORT"][0].isdigit():
                    port_smtp = int(env_data["SMTP_PORT"][0])
            except Exception:
                pass

    h_imap = imap_host or email_cfg.get("imap_host", "") or preset.get("imap_host", "imap.gmail.com")
    if not imap_host:
        h_imap_env = os.getenv("IMAP_HOST", "")
        if h_imap_env:
            h_imap = h_imap_env
        else:
            try:
                from skills import shared_memory
                env_data = shared_memory._read_env()
                if "IMAP_HOST" in env_data:
                    h_imap = env_data["IMAP_HOST"][0]
            except Exception:
                pass

    return u, p, h_smtp, int(port_smtp), h_imap


def _get_smtp_conn(host: str, port: int) -> smtplib.SMTP:
    """Open SMTP connection — uses SSL on port 465, STARTTLS otherwise."""
    if port == 465:
        context = _ssl.create_default_context()
        return smtplib.SMTP_SSL(host, port, context=context, timeout=15)
    srv = smtplib.SMTP(host, port, timeout=15)
    srv.ehlo()
    srv.starttls()
    srv.ehlo()
    return srv


def send_email(
    to: str,
    subject: str,
    body: str,
    html: bool = False,
    cc: str = "",
    bcc: str = "",
    sender_name: str = "",
    reply_to: str = "",
    attachments: Optional[list] = None,
    smtp_host: str = "",
    smtp_port: int = 0,
    username: str = "",
    password: str = "",
) -> str:
    u, p, h, port, _ = _resolve_credentials(username, password, smtp_host, smtp_port)

    if not u:
        return "ERROR: No email username configured. Set email.username in config or pass username parameter."
    if not p:
        return "ERROR: No email password configured. Set email.password in config or pass password parameter."

    to_list  = _parse_recipients(to)
    cc_list  = _parse_recipients(cc)  if cc  else []
    bcc_list = _parse_recipients(bcc) if bcc else []
    all_rcpt = to_list + cc_list + bcc_list

    msg = MIMEMultipart("mixed")
    display_from = _formataddr((sender_name, u)) if sender_name else u
    msg["From"]    = display_from
    msg["To"]      = ", ".join(to_list)
    msg["Subject"] = subject
    if cc_list:
        msg["Cc"] = ", ".join(cc_list)
    if reply_to:
        msg["Reply-To"] = reply_to

    # Body part
    content_type = "html" if html else "plain"
    msg.attach(MIMEText(body, content_type, "utf-8"))

    # Attachments
    if attachments:
        for file_path in attachments:
            path = Path(file_path)
            if not path.exists():
                return f"ERROR: Attachment not found: {file_path}"
            try:
                with open(path, "rb") as f:
                    part = MIMEBase("application", "octet-stream")
                    part.set_payload(f.read())
                _encoders.encode_base64(part)
                part.add_header(
                    "Content-Disposition",
                    "attachment",
                    filename=path.name,
                )
                msg.attach(part)
            except Exception as e:
                return f"ERROR: Could not attach {file_path}: {e}"

    try:
        with _get_smtp_conn(h, port) as srv:
            srv.login(u, p)
            srv.sendmail(u, all_rcpt, msg.as_string())
        summary_parts = [f"Email sent to {', '.join(to_list)}"]
        if cc_list:
            summary_parts.append(f"CC: {', '.join(cc_list)}")
        if bcc_list:
            summary_parts.append(f"BCC: {', '.join(bcc_list)}")
        if attachments:
            summary_parts.append(f"{len(attachments)} attachment(s)")
        return " | ".join(summary_parts)
    except smtplib.SMTPAuthenticationError:
        return (
            f"ERROR: Authentication failed for {u}. "
            "If using Gmail, generate an App Password at https://myaccount.google.com/apppasswords"
        )
    except smtplib.SMTPRecipientsRefused as e:
        return f"ERROR: Recipient refused: {e.recipients}"
    except smtplib.SMTPException as e:
        return f"ERROR (SMTP): {e}"
    except Exception as e:
        return f"ERROR: {e}"


def read_emails(
    imap_host: str = "",
    username: str = "",
    password: str = "",
    folder: str = "INBOX",
    limit: int = 5,
    unread_only: bool = False,
    mark_as_read: bool = False,
) -> str:
    u, p, _, _, h = _resolve_credentials(username, password, imap_host=imap_host)

    if not u:
        return "ERROR: No email username configured."
    if not p:
        return "ERROR: No email password configured."

    limit = min(int(limit), 20)

    try:
        mail = imaplib.IMAP4_SSL(h, timeout=15)
        mail.login(u, p)
        mail.select(folder)
        criterion = "UNSEEN" if unread_only else "ALL"
        _, data = mail.search(None, criterion)
        ids = data[0].split()
        if not ids:
            mail.logout()
            return "No emails found."
        ids = ids[-limit:]
        results = []
        for mid in reversed(ids):
            _, msg_data = mail.fetch(mid, "(RFC822)")
            msg = _email.message_from_bytes(msg_data[0][1])
            subject = _decode_str(msg.get("Subject", "(no subject)"))
            sender  = _decode_str(msg.get("From", ""))
            date    = msg.get("Date", "")
            msg_id  = msg.get("Message-ID", "")
            body    = _extract_body(msg)
            if mark_as_read:
                mail.store(mid, "+FLAGS", "\\Seen")
            results.append(
                f"From: {sender}\nDate: {date}\nSubject: {subject}\n"
                f"Message-ID: {msg_id}\n{body}\n{'─'*40}"
            )
        mail.logout()
        return "\n".join(results)
    except imaplib.IMAP4.error as e:
        return f"ERROR (IMAP): {e}"
    except Exception as e:
        return f"ERROR: {e}"


def search_emails(
    query: str,
    folder: str = "INBOX",
    limit: int = 10,
    since_date: str = "",
    imap_host: str = "",
    username: str = "",
    password: str = "",
) -> str:
    u, p, _, _, h = _resolve_credentials(username, password, imap_host=imap_host)

    if not u:
        return "ERROR: No email username configured."
    if not p:
        return "ERROR: No email password configured."

    limit = min(int(limit), 20)

    # Parse query into IMAP search criteria
    imap_criteria = _build_imap_criteria(query, since_date)

    try:
        mail = imaplib.IMAP4_SSL(h, timeout=15)
        mail.login(u, p)
        mail.select(folder, readonly=True)
        _, data = mail.search(None, imap_criteria)
        ids = data[0].split()
        if not ids:
            mail.logout()
            return f"No emails found matching '{query}'."
        ids = ids[-limit:]
        results = []
        for mid in reversed(ids):
            _, msg_data = mail.fetch(mid, "(RFC822)")
            msg = _email.message_from_bytes(msg_data[0][1])
            subject = _decode_str(msg.get("Subject", "(no subject)"))
            sender  = _decode_str(msg.get("From", ""))
            date    = msg.get("Date", "")
            msg_id  = msg.get("Message-ID", "")
            body    = _extract_body(msg, max_chars=300)
            results.append(
                f"From: {sender}\nDate: {date}\nSubject: {subject}\n"
                f"Message-ID: {msg_id}\n{body}\n{'─'*40}"
            )
        mail.logout()
        return f"Found {len(results)} email(s) for '{query}':\n\n" + "\n".join(results)
    except imaplib.IMAP4.error as e:
        return f"ERROR (IMAP): {e}"
    except Exception as e:
        return f"ERROR: {e}"


def reply_email(
    message_id: str,
    reply_body: str,
    reply_to_sender: str,
    html: bool = False,
    subject: str = "",
    smtp_host: str = "",
    smtp_port: int = 0,
    username: str = "",
    password: str = "",
) -> str:
    u, p, h, port, _ = _resolve_credentials(username, password, smtp_host, smtp_port)

    if not u or not p:
        return "ERROR: Email credentials not configured."

    reply_subject = subject if subject else f"Re: {message_id[:30]}"
    msg = MIMEMultipart()
    msg["From"] = u
    msg["To"] = reply_to_sender
    msg["Subject"] = reply_subject
    msg["In-Reply-To"] = message_id
    msg["References"] = message_id
    msg.attach(MIMEText(reply_body, "html" if html else "plain", "utf-8"))

    try:
        with _get_smtp_conn(h, port) as srv:
            srv.login(u, p)
            srv.sendmail(u, [reply_to_sender], msg.as_string())
        return f"Reply sent to {reply_to_sender}"
    except smtplib.SMTPAuthenticationError:
        return "ERROR: Authentication failed. Check your email credentials or App Password."
    except Exception as e:
        return f"ERROR: {e}"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_body(msg, max_chars: int = 500) -> str:
    """Extract plain text body from email message."""
    if msg.is_multipart():
        # Prefer plain text, fall back to HTML
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and part.get_content_disposition() != "attachment":
                try:
                    payload = part.get_payload(decode=True)
                    charset = part.get_content_charset() or "utf-8"
                    return payload.decode(charset, errors="replace")[:max_chars]
                except Exception:
                    pass
        # Fall back to HTML → strip tags
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                try:
                    import re
                    payload = part.get_payload(decode=True)
                    charset = part.get_content_charset() or "utf-8"
                    text = payload.decode(charset, errors="replace")
                    text = re.sub(r"<[^>]+>", " ", text)
                    text = re.sub(r"\s+", " ", text).strip()
                    return text[:max_chars]
                except Exception:
                    pass
    else:
        try:
            payload = msg.get_payload(decode=True)
            charset = msg.get_content_charset() or "utf-8"
            return payload.decode(charset, errors="replace")[:max_chars]
        except Exception:
            pass
    return "(no body)"


def _build_imap_criteria(query: str, since_date: str = "") -> str:
    """Convert a natural query string into an IMAP search criterion."""
    import re
    criteria_parts = []

    # Parse special prefixes: from:addr, subject:text
    from_match = re.search(r"from:(\S+)", query, re.IGNORECASE)
    subj_match = re.search(r"subject:(.+?)(?:\s+\w+:|$)", query, re.IGNORECASE)

    if from_match:
        criteria_parts.append(f'FROM "{from_match.group(1)}"')
        query = re.sub(r"from:\S+", "", query).strip()
    if subj_match:
        criteria_parts.append(f'SUBJECT "{subj_match.group(1).strip()}"')
        query = re.sub(r"subject:.+?(?=\s+\w+:|$)", "", query).strip()

    # Remaining query → search in subject + body (use OR)
    remaining = query.strip()
    if remaining:
        criteria_parts.append(f'(OR SUBJECT "{remaining}" BODY "{remaining}")')

    if since_date:
        criteria_parts.append(f'SINCE {since_date}')

    return " ".join(criteria_parts) if criteria_parts else "ALL"


# ─── Sent Email Log ───────────────────────────────────────────────────────────

_EMAIL_LOG_PATH = Path.home() / ".Koza" / "email_log.csv"


def _log_sent_email(to_addr: str, subject: str, status: str, note: str = "") -> None:
    """Log a sent email to CSV for tracking."""
    _EMAIL_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    file_exists = _EMAIL_LOG_PATH.exists()
    try:
        with open(_EMAIL_LOG_PATH, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(["timestamp", "to", "subject", "status", "note"])
            writer.writerow([
                time.strftime("%Y-%m-%d %H:%M:%S"),
                to_addr,
                subject[:80],
                status,
                note,
            ])
    except Exception:
        pass  # Silent fail — don't block email sending for logging


def email_log(limit: int = 20) -> str:
    """Show recent sent email log."""
    if not _EMAIL_LOG_PATH.exists():
        return "📭 No sent email log found."
    try:
        with open(_EMAIL_LOG_PATH, "r", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        if not rows:
            return "📭 No entries in email log."
        lines = [f"📧 Sent Emails (last {min(limit, len(rows))} of {len(rows)}):\n"]
        for row in rows[-limit:]:
            status_icon = "✅" if row.get("status", "") == "sent" else "❌"
            lines.append(
                f"  {status_icon} [{row.get('timestamp', '?')}] "
                f"{row.get('to', '?')} — {row.get('subject', '?')[:50]}"
            )
        return "\n".join(lines)
    except Exception as e:
        return f"❌ Error reading log: {e}"


# ─── Batch Send ───────────────────────────────────────────────────────────────

def send_batch_emails(
    recipients: list,
    subject: str,
    body: str,
    html: bool = False,
    personalized: bool = False,
    sender_name: str = "",
    attachments: Optional[list] = None,
    smtp_host: str = "",
    smtp_port: int = 0,
    username: str = "",
    password: str = "",
) -> str:
    """Send the same (or personalized) email to multiple recipients.

    Args:
        recipients: List of email addresses, or list of dicts for personalization:
                    [{"to": "a@x.com", "name": "Ali"}, {"to": "b@x.com", "name": "Veli"}]
        subject: Email subject. Use {name} for personalization.
        body: Email body. Use {name} for personalization.
        personalized: If True, recipients must be dicts with 'to' and 'name'.
        sender_name: Display name for sender.
    """
    u, p, h, port, _ = _resolve_credentials(username, password, smtp_host, smtp_port)

    if not u:
        return "ERROR: No email username configured."
    if not p:
        return "ERROR: No email password configured."

    results = []
    success_count = 0
    fail_count = 0

    for i, recip in enumerate(recipients):
        if personalized and isinstance(recip, dict):
            to_addr = recip.get("to", "")
            name = recip.get("name", "")
        else:
            to_addr = str(recip).strip() if recip else ""
            name = ""

        if not to_addr:
            results.append(f"  #{i+1}: ❌ Invalid address: {recip}")
            fail_count += 1
            continue

        # Personalize subject/body
        p_subject = subject.replace("{name}", name) if name else subject
        p_body = body.replace("{name}", name) if name else body

        # Send (reuse single send logic)
        result = send_email(
            to=to_addr,
            subject=p_subject,
            body=p_body,
            html=html,
            sender_name=sender_name,
            attachments=attachments,
            smtp_host=h, smtp_port=port, username=u, password=p,
        )

        if result.startswith("ERROR"):
            results.append(f"  #{i+1}: ❌ {to_addr} — {result}")
            _log_sent_email(to_addr, p_subject, "failed", result)
            fail_count += 1
        else:
            results.append(f"  #{i+1}: ✅ {to_addr}")
            _log_sent_email(to_addr, p_subject, "sent", result)
            success_count += 1

    summary = f"📧 Batch send complete: {success_count} sent, {fail_count} failed ({len(recipients)} total)\n"
    return summary + "\n".join(results)


# ─── Email Setup (interactive) ────────────────────────────────────────────────

def email_setup() -> str:
    """Interactive email setup — configures SMTP/IMAP credentials."""
    import sys
    if not (sys.stdin and sys.stdin.isatty()):
        return (
            "❌ Non-interactive environment detected.\n"
            "   Please configure your email credentials directly in the Settings panel (under 'Messaging & Sync' -> 'Email') of the GUI interface."
        )

    from cli.ui import _C, _prompt, _prompt_secret

    print(_C("\n  📧 Email Setup\n", "bold", "cyan"))
    print(_C("  ────────────────────────\n", "grey"))

    email_addr = _prompt("Email address", default="").strip()
    if not email_addr:
        return "❌ Email address required."

    preset = _preset_for(email_addr)
    smtp_host = _prompt("SMTP server", default=preset.get("smtp_host", "smtp.gmail.com")).strip()
    smtp_port_str = _prompt("SMTP port", default=str(preset.get("smtp_port", 587))).strip()
    smtp_port = int(smtp_port_str) if smtp_port_str.isdigit() else 587
    imap_host = _prompt("IMAP server", default=preset.get("imap_host", "imap.gmail.com")).strip()

    print(_C("\n  🔑 Password/App Password:\n", "grey"))
    print(_C("  If you are using Gmail, you must obtain an App Password:", "yellow"))
    print(_C("  https://myaccount.google.com/apppasswords\n", "cyan"))
    password = _prompt_secret("Password/App Password")

    # Save to config
    from config import load_config, save_config
    cfg = load_config()
    cfg.setdefault("email", {})
    cfg["email"]["username"] = email_addr
    cfg["email"]["password"] = password
    cfg["email"]["smtp_host"] = smtp_host
    cfg["email"]["smtp_port"] = smtp_port
    cfg["email"]["imap_host"] = imap_host
    save_config(cfg)

    # Re-init
    init_email(cfg)

    return (
        f"✅ Email configured for {email_addr}\n"
        f"   SMTP: {smtp_host}:{smtp_port}\n"
        f"   IMAP: {imap_host}\n"
        f"   Test with: send_email(to='test@example.com', subject='Test', body='Hello!')\n"
    )


HANDLERS = {
    "send_email":        lambda **kw: send_email(**kw),
    "read_emails":       lambda **kw: read_emails(**kw),
    "search_emails":     lambda **kw: search_emails(**kw),
    "reply_email":       lambda **kw: reply_email(**kw),
    "send_batch_emails": lambda **kw: send_batch_emails(**kw),
    "email_log":         lambda limit=20: email_log(int(limit)),
    "email_setup":       lambda: email_setup(),
}
