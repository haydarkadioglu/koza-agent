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
        kwargs = {"model": self._model, "messages": self._normalize_openai_messages(messages)}
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
        kwargs = {"model": self._model, "messages": self._normalize_openai_messages(messages), "stream": True}
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        resp = self._client.chat.completions.create(**kwargs)

        # ── DSML detection helpers ────────────────────────────────────────────
        # DeepSeek occasionally bleeds DSML XML into the text stream instead of
        # using the proper API tool_calls. DSML markers use fullwidth ｜ (U+FF5C).
        _P = "｜"
        _DSML_OPEN  = f"<{_P}"          # earliest sign of a DSML block
        _DSML_CLOSE = f"</{_P}"         # end of a DSML block

        dsml_pattern = re.compile(
            rf"<{_P}{{1,2}}DSML{_P}{{1,2}}tool_calls>(.*?)</{_P}{{1,2}}DSML{_P}{{1,2}}tool_calls>",
            re.DOTALL,
        )
        invoke_pattern = re.compile(
            rf'<{_P}{{1,2}}DSML{_P}{{1,2}}invoke\s+name=["\']([^"\']+)["\']>(.*?)</{_P}{{1,2}}DSML{_P}{{1,2}}invoke>',
            re.DOTALL,
        )
        param_pattern = re.compile(
            rf'<{_P}{{1,2}}DSML{_P}{{1,2}}parameter\s+name=["\']([^"\']+)["\'][^>]*>(.*?)</{_P}{{1,2}}DSML{_P}{{1,2}}parameter>',
            re.DOTALL,
        )

        tool_chunks: dict[int, dict] = {}
        text_buf  = ""   # accumulates ALL emitted text (for DSML post-check)
        pending   = ""   # look-ahead buffer for DSML detection
        # Max chars to hold in pending before we give up and treat as plain text
        _DSML_MAX = 2048

        def _flush_pending_as_text(p: str):
            """Yield pending string and accumulate into text_buf."""
            nonlocal text_buf
            if p:
                text_buf += p
                yield p

        for chunk in resp:
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            delta  = choice.delta

            # ── Proper API tool call chunks ───────────────────────────────────
            if delta.tool_calls:
                # Flush any pending plain text before switching to tool mode
                yield from _flush_pending_as_text(pending)
                pending = ""
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

            token = delta.content or ""
            if not token:
                continue

            pending += token

            # ── DSML look-ahead: only hold back text when we might be in a
            #    DSML block. If no DSML open-marker visible, flush immediately.
            while True:
                dsml_pos = pending.find(_DSML_OPEN)

                if dsml_pos == -1:
                    # No DSML marker anywhere — safe to flush all
                    yield from _flush_pending_as_text(pending)
                    pending = ""
                    break

                # Yield everything before the potential DSML start
                if dsml_pos > 0:
                    safe = pending[:dsml_pos]
                    text_buf += safe
                    yield safe
                    pending = pending[dsml_pos:]

                # Check if the pending buffer already contains a full DSML close
                if _DSML_CLOSE in pending:
                    # Full DSML block captured — keep buffering until stream ends
                    # (we process DSML after the loop)
                    break

                # Overflow guard: if pending is large but no close tag yet,
                # it's not a real DSML block — flush it
                if len(pending) > _DSML_MAX:
                    yield from _flush_pending_as_text(pending)
                    pending = ""
                break

        # ── After stream: flush remaining pending (may contain DSML) ─────────
        # pending at this point either contains a DSML block or leftover text
        text_buf += pending
        pending_remainder = pending

        # ── Yield structured tool chunks from proper API tool_calls ──────────
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

        # ── Post-process pending remainder for DSML bleed-through ────────────
        dsml_counter = [len(tool_chunks)]
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

        clean_remainder = dsml_pattern.sub(_collect_dsml, pending_remainder).strip()

        # Yield any DSML-extracted tool calls
        for tc_event in dsml_tool_yields:
            yield tc_event

        # Yield any non-DSML text that was held in pending
        if clean_remainder:
            yield clean_remainder

    def list_models(self) -> list[str]:
        try:
            return [m.id for m in self._client.models.list()]
        except Exception:
            return ["deepseek-chat", "deepseek-coder", "deepseek-reasoner"]
