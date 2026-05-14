"""WhatsApp messaging — send via Twilio WhatsApp API."""
import os

_account_sid: str = ""
_auth_token: str = ""
_from_number: str = ""
_to_number: str = ""


def init(cfg_whatsapp: dict) -> None:
    global _account_sid, _auth_token, _from_number, _to_number
    _account_sid = cfg_whatsapp.get("account_sid", os.getenv("TWILIO_ACCOUNT_SID", ""))
    _auth_token  = cfg_whatsapp.get("auth_token",  os.getenv("TWILIO_AUTH_TOKEN",  ""))
    _from_number = cfg_whatsapp.get("from_number", os.getenv("TWILIO_FROM_WA",     ""))
    _to_number   = cfg_whatsapp.get("to_number",   os.getenv("TWILIO_TO_WA",       ""))


def send(text: str, to: str = "") -> str:
    if not _account_sid or not _auth_token:
        return "WhatsApp not configured. Set TWILIO_ACCOUNT_SID + TWILIO_AUTH_TOKEN."
    dest = to or _to_number
    if not dest:
        return "No destination number. Set TWILIO_TO_WA."
    try:
        from twilio.rest import Client
        client = Client(_account_sid, _auth_token)
        msg = client.messages.create(
            from_=f"whatsapp:{_from_number}",
            to=f"whatsapp:{dest}",
            body=text,
        )
        return f"✅ WhatsApp sent (SID: {msg.sid})"
    except ImportError:
        return "twilio package not installed (pip install twilio)."
    except Exception as e:
        return f"❌ WhatsApp error: {e}"
