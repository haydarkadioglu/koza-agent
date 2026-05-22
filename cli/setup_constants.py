"""Setup constants — provider lists, model catalogs, and key requirements."""

PROVIDERS = [
    "ollama", "openai", "anthropic", "deepseek", "groq", "openrouter",
    "kimi", "minimax", "zai", "gemini api", "gemini cookie",
    "antigravity manager", "github",
]

PROVIDER_MODELS = {
    "openai":              ["gpt-5.5", "gpt-5.4-mini", "gpt-5-mini", "gpt-4.1", "gpt-4o"],
    "anthropic":           ["claude-opus-4-5", "claude-sonnet-4-5", "claude-haiku-4-5"],
    "deepseek":            ["deepseek-chat", "deepseek-reasoner", "deepseek-coder-v2"],
    "groq":                ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "mixtral-8x7b-32768", "gemma2-9b-it", "deepseek-r1-distill-llama-70b"],
    "openrouter":          ["openai/gpt-4o", "anthropic/claude-3.5-sonnet", "google/gemini-2.0-flash-exp", "deepseek/deepseek-chat", "meta-llama/llama-3.3-70b-instruct"],
    "kimi":                ["kimi-k2-0711-preview", "moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k", "kimi-latest"],
    "minimax":             ["MiniMax-M1", "MiniMax-Text-01", "abab6.5s-chat"],
    "zai":                 ["glm-z1-air", "glm-z1-flash", "glm-4-plus", "glm-4-air", "glm-4-flash"],
    "gemini api":          ["gemini-3.5-flash", "gemini-3.1-flash-lite", "gemini-3-flash-preview", "gemini-3.1-pro-preview", "gemini-pro-latest", "gemini-flash-latest"],
    "gemini cookie":       ["gemini-3.5-flash", "gemini-3.1-flash-lite", "gemini-3-flash", "gemini-3.1-pro", "gemini-3-pro", "gemini-3-flash-thinking", "gemini-3-pro-plus", "gemini-3-flash-advanced", "gemini-3-pro-advanced"],
    "gemini":              ["gemini-3.5-flash", "gemini-3.1-flash-lite", "gemini-3-flash-preview", "gemini-3.1-pro-preview", "gemini-pro-latest", "gemini-flash-latest"],
    "antigravity manager": ["gemini-3.1-pro-high", "gemini-3-flash-agent", "claude-sonnet-4-6", "claude-opus-4-6-thinking", "gpt-oss-120b-medium"],
    "ollama":              ["llama3.2", "mistral", "codellama"],
    "github":              ["gpt-4.1", "gpt-4o", "Meta-Llama-3.1-70B-Instruct"],
}

NEEDS_KEY = {
    "openai", "anthropic", "deepseek", "groq", "openrouter",
    "gemini api", "gemini", "github", "kimi", "minimax", "zai",
}

_OTHER = "other — enter manually"
