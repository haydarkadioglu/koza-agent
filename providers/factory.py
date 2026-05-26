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
    elif name == "kimi":
        from .kimi_provider import KimiProvider
        return KimiProvider(pcfg)
    elif name == "minimax":
        from .minimax_provider import MiniMaxProvider
        return MiniMaxProvider(pcfg)
    elif name == "zai":
        from .zai_provider import ZAIProvider
        return ZAIProvider(pcfg)
    elif name == "antigravity manager":
        from .openai_provider import OpenAIProvider
        pcfg["base_url"] = pcfg.get("base_url", "http://localhost:5188") + "/v1"
        pcfg["api_key"] = "antigravity"
        return OpenAIProvider(pcfg)
    elif name == "ollama":
        from .ollama_provider import OllamaProvider
        return OllamaProvider(pcfg)
    elif name == "github":
        from .github_provider import GitHubProvider
        return GitHubProvider(pcfg)
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

