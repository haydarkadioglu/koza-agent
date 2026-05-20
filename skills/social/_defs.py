"""TOOL_DEFINITIONS for the social skill."""
TOOL_DEFINITIONS = [
    # ── Twitter/X ────────────────────────────────────────────────────────────
    {"type": "function", "function": {
        "name": "twitter_search",
        "description": "Search recent tweets using Twitter/X API v2.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string"},
            "limit": {"type": "integer", "default": 10},
        }, "required": ["query"]},
    }},
    # ── Reddit ───────────────────────────────────────────────────────────────
    {"type": "function", "function": {
        "name": "reddit_search",
        "description": "Search Reddit posts. No API key required.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string"},
            "subreddit": {"type": "string", "default": "", "description": "Optional subreddit filter"},
            "sort": {"type": "string", "default": "relevance", "enum": ["relevance", "hot", "top", "new"]},
            "limit": {"type": "integer", "default": 5},
        }, "required": ["query"]},
    }},
    # ── Mastodon ─────────────────────────────────────────────────────────────
    {"type": "function", "function": {
        "name": "mastodon_post",
        "description": "Post a toot to Mastodon.",
        "parameters": {"type": "object", "properties": {
            "content": {"type": "string"},
            "instance_url": {"type": "string", "default": "https://mastodon.social"},
            "token": {"type": "string", "default": ""},
            "visibility": {"type": "string", "default": "public", "enum": ["public", "unlisted", "private", "direct"]},
        }, "required": ["content"]},
    }},
    # ── Bluesky ──────────────────────────────────────────────────────────────
    {"type": "function", "function": {
        "name": "bluesky_search",
        "description": "Search Bluesky posts (AT Protocol). No auth required for public search.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string"},
            "limit": {"type": "integer", "default": 10},
        }, "required": ["query"]},
    }},
    {"type": "function", "function": {
        "name": "bluesky_post",
        "description": "Post to Bluesky. Requires your handle (e.g. user.bsky.social) and an App Password from Settings.",
        "parameters": {"type": "object", "properties": {
            "text": {"type": "string", "description": "Post text (max 300 chars)"},
            "handle": {"type": "string", "default": "", "description": "Your Bluesky handle"},
            "app_password": {"type": "string", "default": "", "description": "App password from Bluesky settings"},
        }, "required": ["text"]},
    }},
    # ── Hacker News ──────────────────────────────────────────────────────────
    {"type": "function", "function": {
        "name": "hackernews_top",
        "description": "Get top stories from Hacker News. No API key required.",
        "parameters": {"type": "object", "properties": {
            "limit": {"type": "integer", "default": 10},
            "story_type": {"type": "string", "default": "top", "enum": ["top", "new", "best", "ask", "show", "job"]},
        }, "required": []},
    }},
    {"type": "function", "function": {
        "name": "hackernews_search",
        "description": "Search Hacker News stories and comments via Algolia API. No API key required.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string"},
            "limit": {"type": "integer", "default": 5},
            "sort": {"type": "string", "default": "relevance", "enum": ["relevance", "date"]},
        }, "required": ["query"]},
    }},
    # ── LinkedIn ─────────────────────────────────────────────────────────────
    {"type": "function", "function": {
        "name": "linkedin_post",
        "description": "Post a text update to LinkedIn. Requires an OAuth 2.0 access token and your person URN.",
        "parameters": {"type": "object", "properties": {
            "content": {"type": "string", "description": "Post text content"},
            "token": {"type": "string", "default": "", "description": "LinkedIn OAuth 2.0 access token"},
            "person_urn": {"type": "string", "default": "", "description": "Your LinkedIn person URN, e.g. urn:li:person:XXXXXXXX"},
            "visibility": {"type": "string", "default": "PUBLIC", "enum": ["PUBLIC", "CONNECTIONS"]},
        }, "required": ["content"]},
    }},
    # ── Threads (Meta) ───────────────────────────────────────────────────────
    {"type": "function", "function": {
        "name": "threads_post",
        "description": "Post to Threads (Meta). Requires a Threads API access token and your user ID.",
        "parameters": {"type": "object", "properties": {
            "text": {"type": "string", "description": "Post text"},
            "user_id": {"type": "string", "default": "", "description": "Threads user ID"},
            "token": {"type": "string", "default": "", "description": "Threads API access token"},
        }, "required": ["text"]},
    }},
    # ── Instagram ────────────────────────────────────────────────────────────
    {"type": "function", "function": {
        "name": "instagram_post",
        "description": "Post a photo to Instagram via Meta Graph API. Requires a page/user access token and user ID.",
        "parameters": {"type": "object", "properties": {
            "image_url": {"type": "string", "description": "Public URL of the image to post"},
            "caption": {"type": "string", "default": "", "description": "Post caption"},
            "user_id": {"type": "string", "default": "", "description": "Instagram business/creator user ID"},
            "token": {"type": "string", "default": "", "description": "Meta Graph API access token"},
        }, "required": ["image_url"]},
    }},
    {"type": "function", "function": {
        "name": "instagram_get_profile",
        "description": "Get an Instagram business/creator account profile and recent media.",
        "parameters": {"type": "object", "properties": {
            "user_id": {"type": "string", "default": "me", "description": "Instagram user ID or 'me'"},
            "token": {"type": "string", "default": "", "description": "Meta Graph API access token"},
        }, "required": []},
    }},
]
