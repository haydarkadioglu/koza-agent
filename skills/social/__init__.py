"""Social skill package — public API."""
from ._base import set_cfg, get_cfg
from ._defs import TOOL_DEFINITIONS
from ._twitter import twitter_search, twitter_post
from ._reddit import reddit_search
from ._mastodon import mastodon_post
from ._bluesky import bluesky_search, bluesky_post
from ._hackernews import hackernews_top, hackernews_search
from ._linkedin import linkedin_post
from ._threads_instagram import threads_post, instagram_post, instagram_get_profile


def init_social(cfg: dict):
    set_cfg(cfg)


HANDLERS = {
    "twitter_search":        twitter_search,
    "twitter_post":          twitter_post,
    "reddit_search":         reddit_search,
    "mastodon_post":         mastodon_post,
    "bluesky_search":        bluesky_search,
    "bluesky_post":          bluesky_post,
    "hackernews_top":        hackernews_top,
    "hackernews_search":     hackernews_search,
    "linkedin_post":         linkedin_post,
    "threads_post":          threads_post,
    "instagram_post":        instagram_post,
    "instagram_get_profile": instagram_get_profile,
}

__all__ = [
    "init_social", "HANDLERS", "TOOL_DEFINITIONS",
    "twitter_search", "twitter_post",
    "reddit_search", "mastodon_post",
    "bluesky_search", "bluesky_post",
    "hackernews_top", "hackernews_search",
    "linkedin_post", "threads_post", "instagram_post", "instagram_get_profile",
]
