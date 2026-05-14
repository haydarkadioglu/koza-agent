"""Provider factory."""
from .base import LLMProvider


def get_provider(cfg: dict) -> LLMProvider:
    provider_name = cfg.get("provider", "ollama")
    provider_cfg = cfg.get("providers", {}).get(provider_name, {})
    provider_cfg["model"] = cfg.get("model", "") or provider_cfg.get("model", "")

    if provider_name == "openai":
        from .openai_provider import OpenAIProvider
        return OpenAIProvider(provider_cfg)
    elif provider_name == "anthropic":
        from .anthropic_provider import AnthropicProvider
        return AnthropicProvider(provider_cfg)
    elif provider_name == "deepseek":
        from .deepseek_provider import DeepSeekProvider
        return DeepSeekProvider(provider_cfg)
    elif provider_name == "gemini":
        from .gemini_provider import GeminiProvider
        return GeminiProvider(provider_cfg)
    elif provider_name == "ollama":
        from .ollama_provider import OllamaProvider
        return OllamaProvider(provider_cfg)
    else:
        raise ValueError(f"Unknown provider: {provider_name}")
