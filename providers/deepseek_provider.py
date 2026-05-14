"""DeepSeek provider (OpenAI-compatible API)."""
from openai import OpenAI
from typing import Generator
from .base import LLMProvider


class DeepSeekProvider(LLMProvider):
    def __init__(self, cfg: dict):
        self._client = OpenAI(
            api_key=cfg.get("api_key", ""),
            base_url=cfg.get("base_url", "https://api.deepseek.com/v1"),
        )
        self._model = cfg.get("model", "deepseek-chat")

    @property
    def name(self) -> str:
        return "deepseek"

    def chat(self, messages, tools=None, stream=False):
        import json
        kwargs = {"model": self._model, "messages": messages}
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        resp = self._client.chat.completions.create(**kwargs)
        msg = resp.choices[0].message
        tool_calls = None
        if msg.tool_calls:
            tool_calls = [
                {"id": tc.id, "name": tc.function.name, "arguments": json.loads(tc.function.arguments)}
                for tc in msg.tool_calls
            ]
        return {"content": msg.content, "tool_calls": tool_calls}

    def stream_chat(self, messages, tools=None) -> Generator[str, None, None]:
        import json, re
        kwargs = {"model": self._model, "messages": messages, "stream": True}
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        resp = self._client.chat.completions.create(**kwargs)

        # Buffer to detect and skip DSML/XML tool-call bleed-through
        _dsml_buf = ""
        _in_dsml = False

        for chunk in resp:
            choice = chunk.choices[0]
            delta = choice.delta

            # Structured tool_calls in stream — yield sentinel dict
            if delta.tool_calls:
                for tc_chunk in delta.tool_calls:
                    if tc_chunk.function:
                        yield {"__tool_chunk__": True,
                               "index": tc_chunk.index,
                               "id": getattr(tc_chunk, "id", None),
                               "name": getattr(tc_chunk.function, "name", None) or "",
                               "args_chunk": getattr(tc_chunk.function, "arguments", "") or ""}
                continue

            token = delta.content or ""
            if not token:
                continue

            # ── Filter DSML/XML tool bleed-through ───────────────────────────
            _dsml_buf += token
            # Check if we're accumulating a DSML tag
            if "<｜｜DSML｜｜" in _dsml_buf or _in_dsml:
                _in_dsml = True
                # Wait until we see closing pattern before flushing
                if "</｜｜DSML｜｜tool_calls>" in _dsml_buf:
                    _dsml_buf = re.sub(
                        r"<｜｜DSML｜｜tool_calls>.*?</｜｜DSML｜｜tool_calls>",
                        "", _dsml_buf, flags=re.DOTALL
                    )
                    _in_dsml = False
                    if _dsml_buf.strip():
                        yield _dsml_buf
                    _dsml_buf = ""
                # Don't yield while inside DSML block
                continue

            # Flush safe buffer
            if _dsml_buf:
                yield _dsml_buf
                _dsml_buf = ""

        # Flush any remaining safe content
        if _dsml_buf and not _in_dsml:
            yield _dsml_buf

    def list_models(self) -> list[str]:
        try:
            return [m.id for m in self._client.models.list()]
        except Exception:
            return ["deepseek-chat", "deepseek-coder", "deepseek-reasoner"]
