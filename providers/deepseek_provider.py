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

    @property
    def supports_thinking(self) -> bool:
        return "r1" in self._model.lower() or "reasoner" in self._model.lower()

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

    def stream_chat(self, messages, tools=None, cancel_event=None) -> Generator[str, None, None]:
        import json, re
        kwargs = {"model": self._model, "messages": messages, "stream": True}
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        resp = self._client.chat.completions.create(**kwargs)

        # ── Stream text incrementally, buffer tool_call chunks ────────────────
        # Text tokens are yielded immediately as they arrive so that interrupt
        # can stop token consumption. Tool call deltas are buffered because they
        # must be complete before yielding. After the stream ends we check the
        # accumulated text for DSML bleed-through and yield corrections.
        text_buf = ""  # accumulate for post-stream DSML check
        tool_chunks: dict[int, dict] = {}

        for chunk in resp:
            # ── Cancel support ────────────────────────────────────────────
            if cancel_event and cancel_event.is_set():
                resp.close()
                break

            choice = chunk.choices[0]
            delta = choice.delta

            # Buffer tool_call deltas (need complete before yielding)
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index
                    if idx not in tool_chunks:
                        tool_chunks[idx] = {"id": None, "name": "", "args": ""}
                    if getattr(tc, "id", None):
                        tool_chunks[idx]["id"] = tc.id
                    if tc.function:
                        if getattr(tc.function, "name", None):
                            tool_chunks[idx]["name"] += tc.function.name
                        if getattr(tc.function, "arguments", None):
                            tool_chunks[idx]["args"] += tc.function.arguments
                continue

            # Yield text tokens incrementally as they arrive
            token = delta.content or ""
            if token:
                text_buf += token
                yield token

        # ── Yield structured tool chunks (from proper API tool_calls) ─────────
        for idx, stc in sorted(tool_chunks.items()):
            if stc["name"]:
                try:
                    args_parsed = json.loads(stc["args"] or "{}")
                except Exception:
                    args_parsed = {}
                yield {
                    "__tool_chunk__": True,
                    "index": idx,
                    "id": stc["id"] or stc["name"],
                    "name": stc["name"],
                    "args_chunk": json.dumps(args_parsed),
                }

        # ── Post-stream DSML cleanup ─────────────────────────────────────────
        # DeepSeek sometimes bleeds DSML tool-call XML into the text stream
        # even when tools are passed via the API. Since we already yielded the
        # text incrementally, we check the accumulated buffer for DSML remnants
        # and yield tool chunks as corrections if found.
        _SEP = r"\s*[｜|]?\s*[｜|]?\s*"  # 0-2 pipes with optional whitespace
        dsml_pattern = re.compile(
            rf"<{_SEP}DSML{_SEP}tool_calls\s*>(.*?)<\s*/?{_SEP}DSML{_SEP}tool_calls\s*>",
            re.DOTALL
        )
        invoke_pattern = re.compile(
            rf'<{_SEP}DSML{_SEP}invoke\s+name=["\']([^"\']+)["\']>(.*?)<\s*/?{_SEP}DSML{_SEP}invoke\s*>',
            re.DOTALL
        )
        param_pattern = re.compile(
            rf'<{_SEP}DSML{_SEP}parameter\s+name=["\']([^"\']+)["\'][^>]*>(.*?)<\s*/?{_SEP}DSML{_SEP}parameter\s*>',
            re.DOTALL
        )

        dsml_counter = [len(tool_chunks)]  # mutable for closure

        # Extract DSML tool calls embedded in text
        dsml_tool_yields = []
        def _collect_dsml(m):
            block = m.group(1)
            for inv in invoke_pattern.finditer(block):
                tool_name = inv.group(1)
                params = {}
                for p in param_pattern.finditer(inv.group(2)):
                    params[p.group(1)] = p.group(2).strip()
                for k, v in list(params.items()):
                    try:
                        params[k] = int(v)
                    except (ValueError, TypeError):
                        try:
                            params[k] = float(v)
                        except (ValueError, TypeError):
                            pass
                dsml_tool_yields.append({
                    "__tool_chunk__": True,
                    "index": dsml_counter[0],
                    "id": tool_name,
                    "name": tool_name,
                    "args_chunk": json.dumps(params),
                })
                dsml_counter[0] += 1
            return ""

        if dsml_pattern.search(text_buf):
            dsml_pattern.sub(_collect_dsml, text_buf)

            # Yield DSML-extracted tool calls as corrections
            for tc_event in dsml_tool_yields:
                yield tc_event

    def list_models(self) -> list[str]:
        try:
            return [m.id for m in self._client.models.list()]
        except Exception:
            return ["deepseek-chat", "deepseek-coder", "deepseek-reasoner"]
