"""LinkedIn post."""
from ._base import _post_json, get_cfg


def linkedin_post(content: str, token: str = "", person_urn: str = "", visibility: str = "PUBLIC") -> str:
    try:
        cfg = get_cfg()
        tok = token or cfg.get("linkedin_token", "")
        urn = person_urn or cfg.get("linkedin_person_urn", "")
        if not tok:
            return "LinkedIn access token not configured. Add 'linkedin_token' under social in config."
        if not urn:
            return "LinkedIn person URN not configured. Add 'linkedin_person_urn' (e.g. urn:li:person:XXXXXX) under social in config."
        payload = {
            "author": urn,
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {"text": content},
                    "shareMediaCategory": "NONE",
                }
            },
            "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": visibility},
        }
        result = _post_json("https://api.linkedin.com/v2/ugcPosts", payload, {"Authorization": f"Bearer {tok}"})
        return f"✅ LinkedIn post published! ID: {result.get('id', '')}"
    except Exception as e:
        return f"ERROR: {e}"
