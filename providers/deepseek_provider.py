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

        # ── Collect full response first, then post-process ────────────────────
        # DeepSeek sometimes bleeds DSML tool-call XML into the text stream
        # even when tools are passed. We buffer everything and clean up after.
        text_buf = ""
        tool_chunks: dict[int, dict] = {}

        for chunk in resp:
            choice = chunk.choices[0]
            delta = choice.delta

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

            text_buf += delta.content or ""

        # ── Yield structured tool chunks first (from proper API tool_calls) ───
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

        # ── Post-process text: extract any DSML blocks as tool calls ──────────
        # DSML pattern: <｜｜DSML｜｜tool_calls>...<｜｜DSML｜｜invoke name="X">...</...>
        dsml_pattern = re.compile(
            r"<\|+DSML\|+tool_calls>(.*?)</\|+DSML\|+tool_calls>",
            re.DOTALL
        )
        invoke_pattern = re.compile(
            r'<\|+DSML\|+invoke\s+name=["\']([^"\']+)["\']>(.*?)</\|+DSML\|+invoke>',
            re.DOTALL
        )
        param_pattern = re.compile(
            r'<\|+DSML\|+parameter\s+name=["\']([^"\']+)["\'][^>]*>(.*?)</\|+DSML\|+parameter>',
            re.DOTALL
        )

        dsml_idx = len(tool_chunks)
        def _replace_dsml(m):
            nonlocal dsml_idx
            block = m.group(1)
            for inv in invoke_pattern.finditer(block):
                tool_name = inv.group(1)
                params = {}
                for p in param_pattern.finditer(inv.group(2)):
                    params[p.group(1)] = p.group(2).strip()
                # Try to cast numeric params
                for k, v in list(params.items()):
                    try:
                        params[k] = int(v)
                    except (ValueError, TypeError):
                        try:
                            params[k] = float(v)
                        except (ValueError, TypeError):
                            pass
                yield {
                    "__tool_chunk__": True,
                    "index": dsml_idx,
                    "id": tool_name,
                    "name": tool_name,
                    "args_chunk": json.dumps(params),
                }
                dsml_idx += 1
            return ""

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
                    "index": dsml_idx,
                    "id": tool_name,
                    "name": tool_name,
                    "args_chunk": json.dumps(params),
                })
            return ""

        clean_text = dsml_pattern.sub(_collect_dsml, text_buf).strip()

        # Yield DSML-extracted tool calls
        for tc_event in dsml_tool_yields:
            yield tc_event

        # ── Finally yield clean text ──────────────────────────────────────────
        if clean_text and not tool_chunks and not dsml_tool_yields:
            # Pure text response — yield in chunks for a natural feel
            for i in range(0, len(clean_text), 8):
                yield clean_text[i:i+8]
        elif clean_text:
            yield clean_text

    def list_models(self) -> list[str]:
        try:
            return [m.id for m in self._client.models.list()]
        except Exception:
            return ["deepseek-chat", "deepseek-coder", "deepseek-reasoner"]
