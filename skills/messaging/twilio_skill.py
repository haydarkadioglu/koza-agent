"""Twilio skill — SMS, WhatsApp, Voice calls, phone lookup."""
from __future__ import annotations
import os

_account_sid: str = ""
_auth_token: str  = ""
_from_number: str  = ""   # E.164 e.g. +14155238886 (SMS) or whatsapp:+14155238886 (WA)
_wa_from: str      = ""   # WhatsApp sender (whatsapp:+...)
_wa_to: str        = ""   # Default WhatsApp recipient


def init(cfg_twilio: dict) -> None:
    global _account_sid, _auth_token, _from_number, _wa_from, _wa_to
    _account_sid = cfg_twilio.get("account_sid", os.getenv("TWILIO_ACCOUNT_SID", ""))
    _auth_token  = cfg_twilio.get("auth_token",  os.getenv("TWILIO_AUTH_TOKEN",  ""))
    _from_number = cfg_twilio.get("from_number", os.getenv("TWILIO_FROM_NUMBER", ""))
    _wa_from     = cfg_twilio.get("wa_from",     os.getenv("TWILIO_WA_FROM",     ""))
    _wa_to       = cfg_twilio.get("wa_to",       os.getenv("TWILIO_WA_TO",       ""))


def _client():
    if not _account_sid or not _auth_token:
        raise RuntimeError(
            "Twilio not configured. Set twilio.account_sid and twilio.auth_token in config "
            "or TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN env vars."
        )
    try:
        from twilio.rest import Client
        return Client(_account_sid, _auth_token)
    except ImportError:
        raise RuntimeError("twilio package not installed. Run: pip install twilio")


# ── SMS ───────────────────────────────────────────────────────────────────────

def send_sms(to: str, body: str, from_number: str = "") -> str:
    """Send an SMS message."""
    src = from_number or _from_number
    if not src:
        return "ERROR: No Twilio from_number configured. Set twilio.from_number in config."
    if not to.startswith("+"):
        return "ERROR: Phone number must be in E.164 format (e.g. +905551234567)."
    try:
        client = _client()
        msg = client.messages.create(body=body, from_=src, to=to)
        return f"✅ SMS sent to {to} (SID: {msg.sid}, status: {msg.status})"
    except RuntimeError as e:
        return f"ERROR: {e}"
    except Exception as e:
        return f"ERROR (Twilio SMS): {e}"


def list_sms(limit: int = 10, to_filter: str = "", from_filter: str = "") -> str:
    """List recent SMS messages from Twilio account."""
    try:
        client = _client()
        kwargs = {"limit": min(int(limit), 50)}
        if to_filter:
            kwargs["to"] = to_filter
        if from_filter:
            kwargs["from_"] = from_filter
        messages = client.messages.list(**kwargs)
        if not messages:
            return "No messages found."
        lines = []
        for m in messages:
            lines.append(
                f"[{m.date_sent}] {m.direction} | {m.from_} → {m.to}\n"
                f"  Status: {m.status} | Body: {m.body[:100]}"
            )
        return "\n".join(lines)
    except RuntimeError as e:
        return f"ERROR: {e}"
    except Exception as e:
        return f"ERROR: {e}"


# ── WhatsApp ──────────────────────────────────────────────────────────────────

def send_whatsapp(to: str = "", body: str = "", from_wa: str = "") -> str:
    """Send a WhatsApp message via Twilio."""
    src = from_wa or _wa_from or (_from_number and f"whatsapp:{_from_number}")
    dest = to or _wa_to
    if not src:
        return "ERROR: No Twilio WhatsApp from number configured (twilio.wa_from)."
    if not dest:
        return "ERROR: No destination WhatsApp number (pass 'to' or set twilio.wa_to)."
    if not dest.startswith("whatsapp:"):
        dest = f"whatsapp:{dest}"
    if not src.startswith("whatsapp:"):
        src = f"whatsapp:{src}"
    try:
        client = _client()
        msg = client.messages.create(from_=src, to=dest, body=body)
        return f"✅ WhatsApp sent to {dest} (SID: {msg.sid})"
    except RuntimeError as e:
        return f"ERROR: {e}"
    except Exception as e:
        return f"ERROR (Twilio WhatsApp): {e}"


# ── Voice calls ───────────────────────────────────────────────────────────────

def make_call(to: str, message: str = "", twiml: str = "", from_number: str = "") -> str:
    """Make an outbound voice call. Reads a TTS message or executes custom TwiML."""
    src = from_number or _from_number
    if not src:
        return "ERROR: No Twilio from_number configured."
    if not to.startswith("+"):
        return "ERROR: Phone number must be E.164 format (e.g. +905551234567)."
    if not message and not twiml:
        return "ERROR: Provide either message (text to speak) or twiml."
    try:
        client = _client()
        if twiml:
            xml = twiml
        else:
            # Escape XML special chars
            safe_msg = message.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            xml = f'<Response><Say language="tr-TR">{safe_msg}</Say></Response>'
        call = client.calls.create(
            twiml=xml,
            from_=src,
            to=to,
        )
        return f"✅ Call initiated to {to} (SID: {call.sid}, status: {call.status})"
    except RuntimeError as e:
        return f"ERROR: {e}"
    except Exception as e:
        return f"ERROR (Twilio Call): {e}"


def get_call_status(call_sid: str) -> str:
    """Get the status of a Twilio voice call by SID."""
    try:
        client = _client()
        call = client.calls(call_sid).fetch()
        return (
            f"Call {call_sid}: status={call.status}, duration={call.duration}s\n"
            f"  {call.from_} → {call.to} at {call.start_time}"
        )
    except RuntimeError as e:
        return f"ERROR: {e}"
    except Exception as e:
        return f"ERROR: {e}"


# ── Phone lookup ──────────────────────────────────────────────────────────────

def lookup_phone(phone_number: str) -> str:
    """Look up carrier and line type for a phone number (requires Twilio Lookup add-on)."""
    if not phone_number.startswith("+"):
        return "ERROR: Phone number must be E.164 format (e.g. +905551234567)."
    try:
        client = _client()
        result = client.lookups.v1.phone_numbers(phone_number).fetch(type=["carrier"])
        carrier = result.carrier or {}
        return (
            f"Phone: {result.phone_number}\n"
            f"  Country: {result.country_code}\n"
            f"  Carrier: {carrier.get('name', 'unknown')}\n"
            f"  Line type: {carrier.get('type', 'unknown')}"
        )
    except RuntimeError as e:
        return f"ERROR: {e}"
    except Exception as e:
        return f"ERROR (Lookup): {e}"


# ── Account info ──────────────────────────────────────────────────────────────

def get_account_info() -> str:
    """Return Twilio account balance and status."""
    try:
        client = _client()
        acc = client.api.accounts(_account_sid).fetch()
        balance = client.api.accounts(_account_sid).balance.fetch()
        return (
            f"Twilio Account: {acc.friendly_name}\n"
            f"  SID: {_account_sid}\n"
            f"  Status: {acc.status}\n"
            f"  Balance: {balance.balance} {balance.currency}"
        )
    except RuntimeError as e:
        return f"ERROR: {e}"
    except Exception as e:
        return f"ERROR: {e}"
