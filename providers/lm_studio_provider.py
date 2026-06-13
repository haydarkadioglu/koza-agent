"""LM Studio provider (Local OpenAI API compatible)."""
from .openai_provider import OpenAIProvider

class LMStudioProvider(OpenAIProvider):
    def __init__(self, cfg: dict):
        cfg = cfg.copy()
        # LM Studio default endpoint
        if "base_url" not in cfg or not cfg["base_url"]:
            cfg["base_url"] = "http://localhost:1234/v1"
        # LM Studio doesn't strictly need a real API key, but openai client requires one
        if "api_key" not in cfg or not cfg["api_key"]:
            cfg["api_key"] = "lm-studio"
            
        super().__init__(cfg)

    @property
    def name(self) -> str:
        return "lm_studio"

    @property
    def supports_thinking(self) -> bool:
        return False

    @property
    def supports_vision(self) -> bool:
        return True

    def list_models(self) -> list[str]:
        try:
            return super().list_models()
        except Exception:
            return ["local-model"]
