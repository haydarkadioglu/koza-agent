"""Email skill — SMTP send, IMAP read."""
import smtplib
import imaplib
import email as _email
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "send_email",
            "description": "Send an email via SMTP.",
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {"type": "string"},
                    "subject": {"type": "string"},
                    "body": {"type": "string"},
                    "smtp_host": {"type": "string", "default": "smtp.gmail.com"},
                    "smtp_port": {"type": "integer", "default": 587},
                    "username": {"type": "string", "default": ""},
                    "password": {"type": "string", "default": ""},
                },
                "required": ["to", "subject", "body"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_emails",
            "description": "Read recent emails from an IMAP mailbox.",
            "parameters": {
                "type": "object",
                "properties": {
                    "imap_host": {"type": "string", "default": "imap.gmail.com"},
                    "username": {"type": "string", "default": ""},
                    "password": {"type": "string", "default": ""},
                    "folder": {"type": "string", "default": "INBOX"},
                    "limit": {"type": "integer", "default": 5},
                },
                "required": [],
            },
        },
    },
]

_email_cfg: dict = {}


def init_email(cfg: dict):
    global _email_cfg
    _email_cfg = cfg.get("email", {})


def send_email(to: str, subject: str, body: str,
               smtp_host: str = "smtp.gmail.com", smtp_port: int = 587,
               username: str = "", password: str = "") -> str:
    u = username or _email_cfg.get("username", "")
    p = password or _email_cfg.get("password", "")
    h = smtp_host or _email_cfg.get("smtp_host", "smtp.gmail.com")
    try:
        msg = MIMEMultipart()
        msg["From"] = u
        msg["To"] = to
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))
        with smtplib.SMTP(h, smtp_port) as srv:
            srv.ehlo()
            srv.starttls()
            srv.login(u, p)
            srv.sendmail(u, to, msg.as_string())
        return f"Email sent to {to}"
    except Exception as e:
        return f"ERROR: {e}"


def read_emails(imap_host: str = "imap.gmail.com", username: str = "",
                password: str = "", folder: str = "INBOX", limit: int = 5) -> str:
    u = username or _email_cfg.get("username", "")
    p = password or _email_cfg.get("password", "")
    h = imap_host or _email_cfg.get("imap_host", "imap.gmail.com")
    try:
        mail = imaplib.IMAP4_SSL(h)
        mail.login(u, p)
        mail.select(folder)
        _, data = mail.search(None, "ALL")
        ids = data[0].split()[-limit:]
        results = []
        for mid in reversed(ids):
            _, msg_data = mail.fetch(mid, "(RFC822)")
            msg = _email.message_from_bytes(msg_data[0][1])
            subject = msg.get("Subject", "(no subject)")
            sender = msg.get("From", "")
            date = msg.get("Date", "")
            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        body = part.get_payload(decode=True).decode("utf-8", errors="replace")[:200]
                        break
            else:
                body = msg.get_payload(decode=True).decode("utf-8", errors="replace")[:200]
            results.append(f"From: {sender}\nDate: {date}\nSubject: {subject}\n{body}\n{'-'*40}")
        mail.logout()
        return "\n".join(results) if results else "No emails found."
    except Exception as e:
        return f"ERROR: {e}"


HANDLERS = {"send_email": send_email, "read_emails": read_emails}
