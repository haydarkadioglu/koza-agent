"""Media skill — Spotify, YouTube search, GIF search."""
import os
import urllib.request
import urllib.parse
import json

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "spotify_search",
            "description": "Search Spotify for tracks, albums, or artists.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "type": {"type": "string", "default": "track", "enum": ["track", "album", "artist", "playlist"]},
                    "limit": {"type": "integer", "default": 5},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "youtube_search",
            "description": "Search YouTube for videos (returns title, URL, channel).",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "default": 5},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "youtube_download",
            "description": "Download a YouTube video or audio using yt-dlp.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "audio_only": {"type": "boolean", "default": False},
                    "output_dir": {"type": "string", "default": "."},
                },
                "required": ["url"],
            },
        },
    },
]

_spotify_token: str = ""
_tenor_key: str = ""


def init_media(cfg: dict):
    global _spotify_token, _tenor_key
    _tenor_key = cfg.get("tenor_api_key", "")


def spotify_search(query: str, type: str = "track", limit: int = 5) -> str:
    try:
        import spotipy
        from spotipy.oauth2 import SpotifyClientCredentials
        sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials())
        results = sp.search(q=query, type=type, limit=limit)
        items = results[f"{type}s"]["items"]
        lines = []
        for item in items:
            if type == "track":
                artists = ", ".join(a["name"] for a in item["artists"])
                lines.append(f"🎵 {item['name']} — {artists}\n   {item['external_urls']['spotify']}")
            elif type == "artist":
                lines.append(f"🎤 {item['name']} ({item['followers']['total']:,} followers)\n   {item['external_urls']['spotify']}")
            else:
                lines.append(f"📀 {item['name']}\n   {item['external_urls']['spotify']}")
        return "\n\n".join(lines) if lines else "No results."
    except ImportError:
        return "spotipy not installed. Run: pip install spotipy"
    except Exception as e:
        return f"ERROR: {e} (Set SPOTIPY_CLIENT_ID and SPOTIPY_CLIENT_SECRET env vars)"


def youtube_search(query: str, limit: int = 5) -> str:
    try:
        # Use yt-dlp's search functionality
        import subprocess
        result = subprocess.run(
            ["yt-dlp", f"ytsearch{limit}:{query}", "--print", "%(title)s\t%(webpage_url)s\t%(channel)s", "--no-download"],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0 or not result.stdout.strip():
            raise Exception(result.stderr.strip() or "No results")
        lines = []
        for line in result.stdout.strip().splitlines():
            parts = line.split("\t")
            if len(parts) >= 2:
                title = parts[0]
                url = parts[1]
                channel = parts[2] if len(parts) > 2 else ""
                lines.append(f"▶ {title}\n  {url}  [{channel}]")
        return "\n\n".join(lines) if lines else "No results."
    except FileNotFoundError:
        return "yt-dlp not installed. Run: pip install yt-dlp"
    except Exception as e:
        return f"ERROR: {e}"


def gif_search(query: str, limit: int = 3) -> str:
    try:
        key = _tenor_key or os.environ.get("TENOR_API_KEY", "")
        if not key:
            return "ERROR: Tenor API key not configured. Set tenor_api_key in config or TENOR_API_KEY env var."
        encoded = urllib.parse.quote_plus(query)
        url = f"https://tenor.googleapis.com/v2/search?q={encoded}&key={key}&limit={limit}"
        req = urllib.request.Request(url, headers={"User-Agent": "KozaAgent/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        results = data.get("results", [])
        if not results:
            return "No GIFs found."
        lines = []
        for r in results:
            title = r.get("content_description", r.get("id", ""))
            gif_url = r.get("media_formats", {}).get("gif", {}).get("url", "")
            lines.append(f"🎞 {title}\n   {gif_url}")
        return "\n\n".join(lines)
    except Exception as e:
        return f"ERROR: {e}"


def youtube_download(url: str, audio_only: bool = False, output_dir: str = ".") -> str:
    try:
        import subprocess
        cmd = ["yt-dlp", url, "-P", output_dir]
        if audio_only:
            cmd += ["-x", "--audio-format", "mp3"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        return (result.stdout + result.stderr).strip()[-1000:] or "Download complete."
    except FileNotFoundError:
        return "yt-dlp not installed. Run: pip install yt-dlp"
    except Exception as e:
        return f"ERROR: {e}"


HANDLERS = {
    "spotify_search": spotify_search,
    "youtube_search": youtube_search,
    "gif_search": gif_search,
    "youtube_download": youtube_download,
}
