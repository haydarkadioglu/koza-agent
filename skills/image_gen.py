"""Image and video generation skill — OpenAI DALL-E 3, Google Imagen, and Veo."""
from __future__ import annotations
import os
import tempfile
import time

# Providers that support image generation
IMAGE_CAPABLE_PROVIDERS = {"openai", "gemini"}


def generate_image(prompt: str, size: str = "1024x1024", save_path: str = "",
                   model: str = "") -> str:
    """Generate an image from a text prompt.

    Uses DALL-E 3 for OpenAI providers.
    For Gemini: cookie mode uses Imagen Nano (free with Pro), api_key mode uses Imagen 3.
    Returns the local file path of the saved image, or an error string.
    """
    from config import load_config
    cfg = load_config()
    provider = cfg.get("provider", "").lower()

    if provider == "openai":
        return _openai_generate(prompt, size, save_path, cfg)
    elif provider == "gemini":
        p_cfg = cfg.get("providers", {}).get("gemini", {})
        auth = p_cfg.get("auth", "api_key").lower()
        if auth == "cookie":
            return _gemini_cookie_generate_image(prompt, save_path, model or "imagen-nano", cfg)
        return _gemini_generate(prompt, size, save_path, cfg)
    else:
        return (
            f"❌ Image generation not supported for provider '{provider}'. "
            f"Switch to 'openai' or 'gemini' to use this feature."
        )


def generate_video(prompt: str, save_path: str = "", model: str = "veo-2") -> str:
    """Generate a video from a text prompt using Veo (Gemini Pro account required).

    Only works with Gemini cookie auth mode and a Pro account.
    Returns the local file path of the saved video, or an error string.
    """
    from config import load_config
    cfg = load_config()
    provider = cfg.get("provider", "").lower()

    if provider != "gemini":
        return "❌ Video generation requires Gemini provider with cookie auth (Pro account)."

    p_cfg = cfg.get("providers", {}).get("gemini", {})
    auth = p_cfg.get("auth", "api_key").lower()
    if auth != "cookie":
        return "❌ Video generation requires Gemini cookie auth mode (Pro account)."

    return _gemini_cookie_generate_video(prompt, save_path, model, cfg)


def _tmp_path(ext: str = "png") -> str:
    return os.path.join(tempfile.gettempdir(), f"koza_img_{int(time.time())}.{ext}")


def _download(url: str, save_path: str) -> str:
    import requests
    path = save_path or _tmp_path()
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    with open(path, "wb") as f:
        f.write(r.content)
    return path


def _openai_generate(prompt: str, size: str, save_path: str, cfg: dict) -> str:
    try:
        from openai import OpenAI
        p_cfg = cfg.get("providers", {}).get("openai", {})
        client = OpenAI(
            api_key=p_cfg.get("api_key", ""),
            base_url=p_cfg.get("base_url", "https://api.openai.com/v1"),
        )
        resp = client.images.generate(
            model="dall-e-3",
            prompt=prompt,
            size=size,
            n=1,
            response_format="url",
        )
        url = resp.data[0].url
        path = _download(url, save_path)
        return path
    except Exception as e:
        return f"❌ Image generation failed: {e}"


def _gemini_generate(prompt: str, size: str, save_path: str, cfg: dict) -> str:
    try:
        from google import genai
        from google.genai import types
        p_cfg = cfg.get("providers", {}).get("gemini", {})
        api_key = p_cfg.get("api_key", "")
        if not api_key:
            return "❌ Gemini API key not configured. Run 'koza setup'."
        client = genai.Client(api_key=api_key)
        resp = client.models.generate_images(
            model="imagen-3.0-generate-002",
            prompt=prompt,
            config=types.GenerateImagesConfig(number_of_images=1),
        )
        img_bytes = resp.generated_images[0].image.image_bytes
        path = save_path or _tmp_path()
        with open(path, "wb") as f:
            f.write(img_bytes)
        return path
    except Exception as e:
        return f"❌ Image generation failed: {e}"


def _gemini_cookie_generate_image(prompt: str, save_path: str, model: str, cfg: dict) -> str:
    try:
        from providers.gemini_provider import GeminiProvider
        p_cfg = cfg.get("providers", {}).get("gemini", {})
        provider = GeminiProvider(p_cfg)
        return provider.generate_image_cookie(prompt, model_name=model, save_path=save_path)
    except Exception as e:
        return f"❌ Cookie image generation failed: {e}"


def _gemini_cookie_generate_video(prompt: str, save_path: str, model: str, cfg: dict) -> str:
    try:
        from providers.gemini_provider import GeminiProvider
        p_cfg = cfg.get("providers", {}).get("gemini", {})
        provider = GeminiProvider(p_cfg)
        return provider.generate_video_cookie(prompt, model_name=model, save_path=save_path)
    except Exception as e:
        return f"❌ Cookie video generation failed: {e}"


TOOL_DEFINITIONS = [
    {
        "name": "generate_image",
        "description": (
            "Generate an image from a text prompt using the current AI provider. "
            "Supported: openai (DALL-E 3), gemini api_key (Imagen 3), gemini cookie (Imagen Nano — free with Pro). "
            "Returns the local file path of the saved image. "
            "Use telegram_send_photo afterwards to send it via Telegram."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Detailed description of the image to generate",
                },
                "size": {
                    "type": "string",
                    "description": "Image size: 1024x1024 (default), 1792x1024 (landscape), 1024x1792 (portrait). OpenAI only.",
                    "default": "1024x1024",
                },
                "save_path": {
                    "type": "string",
                    "description": "Optional file path to save the image. If omitted, saves to a temp file.",
                },
                "model": {
                    "type": "string",
                    "description": "Image model for Gemini cookie mode: 'imagen-nano' (default, free), 'imagen-banana', 'imagen-3'.",
                    "default": "imagen-nano",
                },
            },
            "required": ["prompt"],
        },
    },
    {
        "name": "generate_video",
        "description": (
            "Generate a video from a text prompt using Veo (Google). "
            "Requires Gemini cookie auth with a Pro account. "
            "Returns the local file path of the saved .mp4 video. "
            "Use telegram_send_video afterwards to send it via Telegram."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Detailed description of the video to generate",
                },
                "save_path": {
                    "type": "string",
                    "description": "Optional file path to save the video (.mp4). If omitted, saves to a temp file.",
                },
                "model": {
                    "type": "string",
                    "description": "Video model: 'veo-2' (default)",
                    "default": "veo-2",
                },
            },
            "required": ["prompt"],
        },
    },
]

HANDLERS: dict = {
    "generate_image": lambda prompt, size="1024x1024", save_path="", model="imagen-nano": generate_image(prompt, size, save_path, model),
    "generate_video": lambda prompt, save_path="", model="veo-2": generate_video(prompt, save_path, model),
}

