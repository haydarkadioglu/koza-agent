import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from providers.anthropic_provider import AnthropicProvider
from providers.gemini_provider import GeminiProvider

def test_anthropic_custom_base_url(monkeypatch):
    # Mock anthropic.Anthropic to check arguments passed to it
    class MockAnthropic:
        def __init__(self, api_key=None, base_url=None):
            self.api_key = api_key
            self.base_url = base_url

    import anthropic
    monkeypatch.setattr(anthropic, "Anthropic", MockAnthropic)

    cfg = {
        "api_key": "test-key",
        "base_url": "https://custom-anthropic-endpoint.com/v1",
        "model": "claude-3-5-sonnet-20241022"
    }

    provider = AnthropicProvider(cfg)
    assert provider._client.base_url == "https://custom-anthropic-endpoint.com/v1"
    assert provider._client.api_key == "test-key"

def test_gemini_custom_base_url(monkeypatch):
    # Mock genai.Client
    class MockClient:
        def __init__(self, api_key=None, credentials=None, http_options=None):
            self.api_key = api_key
            self.http_options = http_options

    from google import genai
    monkeypatch.setattr(genai, "Client", MockClient)

    cfg = {
        "api_key": "test-gemini-key",
        "base_url": "https://custom-gemini-endpoint.com/v1",
        "model": "gemini-2.5-flash"
    }

    provider = GeminiProvider(cfg)
    assert provider._client.api_key == "test-gemini-key"
    assert provider._client.http_options == {"base_url": "https://custom-gemini-endpoint.com/v1"}
