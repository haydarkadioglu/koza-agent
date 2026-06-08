"""Setup constants — provider lists, model catalogs, and key requirements."""

PROVIDERS = [
    "ollama", "openai", "anthropic", "deepseek", "groq", "openrouter",
    "kimi", "minimax", "zai", "gemini api", "github", "google-oauth", "codex",
]

PROVIDER_MODELS = {
    "openai":              ["gpt-5.5", "gpt-5.4-mini", "gpt-5-mini", "gpt-4.1", "gpt-4o"],
    "anthropic":           ["claude-opus-4-5", "claude-sonnet-4-5", "claude-haiku-4-5"],
    "deepseek":            ["deepseek-chat", "deepseek-reasoner", "deepseek-coder-v2"],
    "groq":                ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "mixtral-8x7b-32768", "gemma2-9b-it", "deepseek-r1-distill-llama-70b"],
    "openrouter":          [
        "openai/gpt-4o", "openai/gpt-4o-mini", "openai/o3", "openai/o4-mini",
        "anthropic/claude-opus-4", "anthropic/claude-sonnet-4-5", "anthropic/claude-haiku-3-5",
        "google/gemini-2.5-pro", "google/gemini-2.5-flash",
        "deepseek/deepseek-r1", "deepseek/deepseek-chat-v3-0324",
        "meta-llama/llama-4-maverick", "meta-llama/llama-3.3-70b-instruct",
        "qwen/qwen3-235b-a22b", "qwen/qwq-32b",
        "mistralai/mistral-large-2411",
    ],
    "kimi":                ["kimi-k2-0711-preview", "moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k", "kimi-latest"],
    "minimax":             ["MiniMax-M1", "MiniMax-Text-01", "abab6.5s-chat"],
    "zai":                 ["glm-z1-air", "glm-z1-flash", "glm-4-plus", "glm-4-air", "glm-4-flash"],
    "gemini api":          ["gemini-3.5-flash", "gemini-3.1-flash-lite", "gemini-3-flash-preview", "gemini-3.1-pro-preview", "gemini-pro-latest", "gemini-flash-latest"],
    "gemini cli":          ["gemini-3.5-flash", "gemini-3.1-flash-lite", "gemini-3-flash-preview", "gemini-3.1-pro-preview", "gemini-pro-latest", "gemini-flash-latest"],
    "gemini":              ["gemini-3.5-flash", "gemini-3.1-flash-lite", "gemini-3-flash-preview", "gemini-3.1-pro-preview", "gemini-pro-latest", "gemini-flash-latest"],
    "ollama":              ["llama3.2", "mistral", "codellama"],
    "github":              ["gpt-4.1", "gpt-4o", "Meta-Llama-3.1-70B-Instruct"],
    "google-oauth":        ["gemini-3.5-flash", "gemini-3.1-flash-lite", "gemini-3.1-pro-preview", "gemini-3-flash-preview", "gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.0-flash", "gemini-2.0-flash-lite"],
    "codex":               ["o4-mini", "o3", "o4-mini-high", "gpt-4.1", "gpt-4.1-nano", "gpt-4.1-mini", "gpt-4o", "gpt-4o-mini"],
}

NEEDS_KEY = {
    "openai", "anthropic", "deepseek", "groq", "openrouter",
    "gemini api", "gemini", "github", "kimi", "minimax", "zai", "codex",
}

_OTHER = "other — enter manually"
