"""Email skill — SMTP send, IMAP read, search, reply."""
import smtplib
import imaplib
import email as _email
import ssl as _ssl
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
]

_email_cfg: dict = {}


def init_email(cfg: dict):
    global _email_cfg
    _email_cfg = cfg.get("email", {})


def _get_smtp_conn(host: str, port: int) -> smtplib.SMTP:
    """Open SMTP connection — uses SSL on port 465, STARTTLS otherwise."""
    if port == 465:
        context = _ssl.create_default_context()
        return smtplib.SMTP_SSL(host, port, context=context)
    srv = smtplib.SMTP(host, port)
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
    u = username or _email_cfg.get("username", "")
    p = password or _email_cfg.get("password", "")

    # Auto-detect host/port from sender email domain
    preset = _preset_for(u)
    h = smtp_host or _email_cfg.get("smtp_host", "") or preset.get("smtp_host", "smtp.gmail.com")
    port = smtp_port or _email_cfg.get("smtp_port", 0) or preset.get("smtp_port", 587)

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
    u = username or _email_cfg.get("username", "")
    p = password or _email_cfg.get("password", "")
    preset = _preset_for(u)
    h = imap_host or _email_cfg.get("imap_host", "") or preset.get("imap_host", "imap.gmail.com")

    if not u:
        return "ERROR: No email username configured."
    if not p:
        return "ERROR: No email password configured."

    limit = min(int(limit), 20)

    try:
        mail = imaplib.IMAP4_SSL(h)
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
    u = username or _email_cfg.get("username", "")
    p = password or _email_cfg.get("password", "")
    preset = _preset_for(u)
    h = imap_host or _email_cfg.get("imap_host", "") or preset.get("imap_host", "imap.gmail.com")

    if not u:
        return "ERROR: No email username configured."
    if not p:
        return "ERROR: No email password configured."

    limit = min(int(limit), 20)

    # Parse query into IMAP search criteria
    imap_criteria = _build_imap_criteria(query, since_date)

    try:
        mail = imaplib.IMAP4_SSL(h)
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
    u = username or _email_cfg.get("username", "")
    p = password or _email_cfg.get("password", "")
    preset = _preset_for(u)
    h = smtp_host or _email_cfg.get("smtp_host", "") or preset.get("smtp_host", "smtp.gmail.com")
    port = smtp_port or _email_cfg.get("smtp_port", 0) or preset.get("smtp_port", 587)

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


HANDLERS = {
    "send_email":   lambda **kw: send_email(**kw),
    "read_emails":  lambda **kw: read_emails(**kw),
    "search_emails": lambda **kw: search_emails(**kw),
    "reply_email":  lambda **kw: reply_email(**kw),
}
