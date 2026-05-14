"""Productivity skill — Google Calendar, Google Sheets, Airtable."""
import json
import urllib.request
import urllib.parse

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "google_calendar_list",
            "description": "List upcoming Google Calendar events.",
            "parameters": {
                "type": "object",
                "properties": {
                    "max_results": {"type": "integer", "default": 10},
                    "calendar_id": {"type": "string", "default": "primary"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "google_calendar_create",
            "description": "Create a Google Calendar event.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "start": {"type": "string", "description": "ISO datetime, e.g. 2025-06-01T10:00:00"},
                    "end": {"type": "string"},
                    "description": {"type": "string", "default": ""},
                    "calendar_id": {"type": "string", "default": "primary"},
                },
                "required": ["title", "start", "end"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "google_sheets_read",
            "description": "Read data from a Google Sheets spreadsheet.",
            "parameters": {
                "type": "object",
                "properties": {
                    "spreadsheet_id": {"type": "string"},
                    "range": {"type": "string", "default": "Sheet1!A1:Z100"},
                },
                "required": ["spreadsheet_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "airtable_query",
            "description": "Query an Airtable base and table.",
            "parameters": {
                "type": "object",
                "properties": {
                    "base_id": {"type": "string"},
                    "table_name": {"type": "string"},
                    "filter_formula": {"type": "string", "default": ""},
                    "max_records": {"type": "integer", "default": 20},
                },
                "required": ["base_id", "table_name"],
            },
        },
    },
]

_productivity_cfg: dict = {}


def init_productivity(cfg: dict):
    global _productivity_cfg
    _productivity_cfg = cfg.get("productivity", {})


def _get_google_credentials():
    try:
        import google.auth
        from google.auth.transport.requests import Request as GoogleRequest
        creds, _ = google.auth.default(scopes=[
            "https://www.googleapis.com/auth/calendar",
            "https://www.googleapis.com/auth/spreadsheets.readonly",
        ])
        creds.refresh(GoogleRequest())
        return creds.token
    except Exception:
        return _productivity_cfg.get("google_token", "")


def google_calendar_list(max_results: int = 10, calendar_id: str = "primary") -> str:
    try:
        from googleapiclient.discovery import build
        import google.auth
        creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/calendar.readonly"])
        service = build("calendar", "v3", credentials=creds)
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        result = service.events().list(
            calendarId=calendar_id, timeMin=now,
            maxResults=max_results, singleEvents=True, orderBy="startTime"
        ).execute()
        events = result.get("items", [])
        if not events:
            return "No upcoming events."
        lines = []
        for e in events:
            start = e["start"].get("dateTime", e["start"].get("date", ""))[:16]
            lines.append(f"📅 {start}  {e['summary']}")
        return "\n".join(lines)
    except ImportError:
        return "google-api-python-client not installed. Run: pip install google-api-python-client google-auth-httplib2"
    except Exception as e:
        return f"ERROR: {e} (Configure Google ADC or service account)"


def google_calendar_create(title: str, start: str, end: str,
                            description: str = "", calendar_id: str = "primary") -> str:
    try:
        from googleapiclient.discovery import build
        import google.auth
        creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/calendar"])
        service = build("calendar", "v3", credentials=creds)
        event = {
            "summary": title,
            "description": description,
            "start": {"dateTime": start, "timeZone": "UTC"},
            "end": {"dateTime": end, "timeZone": "UTC"},
        }
        result = service.events().insert(calendarId=calendar_id, body=event).execute()
        return f"Event created: {result['summary']}\nLink: {result.get('htmlLink','')}"
    except ImportError:
        return "google-api-python-client not installed."
    except Exception as e:
        return f"ERROR: {e}"


def google_sheets_read(spreadsheet_id: str, range: str = "Sheet1!A1:Z100") -> str:
    try:
        from googleapiclient.discovery import build
        import google.auth
        creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"])
        service = build("sheets", "v4", credentials=creds)
        result = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id, range=range
        ).execute()
        rows = result.get("values", [])
        if not rows:
            return "No data found."
        lines = ["\t".join(str(c) for c in row) for row in rows]
        return "\n".join(lines)
    except ImportError:
        return "google-api-python-client not installed."
    except Exception as e:
        return f"ERROR: {e}"


def airtable_query(base_id: str, table_name: str, filter_formula: str = "", max_records: int = 20) -> str:
    try:
        token = _productivity_cfg.get("airtable_token", "")
        if not token:
            return "Airtable token not configured. Add 'airtable_token' to productivity config."
        params = {"maxRecords": max_records, "view": "Grid view"}
        if filter_formula:
            params["filterByFormula"] = filter_formula
        query = urllib.parse.urlencode(params)
        url = f"https://api.airtable.com/v0/{base_id}/{urllib.parse.quote(table_name)}?{query}"
        req = urllib.request.Request(
            url, headers={"Authorization": f"Bearer {token}", "User-Agent": "KozaAgent/1.0"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        records = data.get("records", [])
        if not records:
            return "No records found."
        lines = []
        for r in records:
            fields = r.get("fields", {})
            lines.append(f"[{r['id']}] " + "  |  ".join(f"{k}: {v}" for k, v in list(fields.items())[:5]))
        return "\n".join(lines)
    except Exception as e:
        return f"ERROR: {e}"


HANDLERS = {
    "google_calendar_list": google_calendar_list,
    "google_calendar_create": google_calendar_create,
    "google_sheets_read": google_sheets_read,
    "airtable_query": airtable_query,
}
