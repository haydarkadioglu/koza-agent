"""Provider factory."""
from .base import LLMProvider


def _build_provider(name: str, cfg: dict, model: str) -> LLMProvider:
    pcfg = cfg.get("providers", {}).get(name, {})
    pcfg = {**pcfg, "model": model or pcfg.get("model", "")}
    if name == "openai":
        from .openai_provider import OpenAIProvider
        return OpenAIProvider(pcfg)
    elif name == "anthropic":
        from .anthropic_provider import AnthropicProvider
        return AnthropicProvider(pcfg)
    elif name == "deepseek":
        from .deepseek_provider import DeepSeekProvider
        return DeepSeekProvider(pcfg)
    elif name == "gemini":
        from .gemini_provider import GeminiProvider
        return GeminiProvider(pcfg)
    elif name == "ollama":
        from .ollama_provider import OllamaProvider
        return OllamaProvider(pcfg)
    else:
        raise ValueError(f"Unknown provider: {name}")


def get_provider(cfg: dict) -> LLMProvider:
    primary_name = cfg.get("provider", "ollama")
    model = cfg.get("model", "")
    primary = _build_provider(primary_name, cfg, model)

    fallback_name = cfg.get("fallback_provider", "")
    if fallback_name and fallback_name != primary_name:
        fallback_model = cfg.get("fallback_model", "")
        fallback = _build_provider(fallback_name, cfg, fallback_model)
        from .fallback_provider import FallbackProvider
        return FallbackProvider(primary, fallback)

    return primary

