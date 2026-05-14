"""GitHub Models provider — OpenAI-compatible API via github.com/marketplace/models."""
from .openai_provider import OpenAIProvider


class GitHubProvider(OpenAIProvider):
    def __init__(self, cfg: dict):
        token = cfg.get("token") or cfg.get("api_key", "")
        super().__init__({
            "api_key": token or "ghp-placeholder",
            "base_url": cfg.get("base_url", "https://models.inference.ai.azure.com"),
            "model": cfg.get("model", "gpt-4o"),
        })

    @property
    def name(self) -> str:
        return "github"
