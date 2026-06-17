"""Context window management for the Koza agent.

Handles message compaction, rolling summary, trimming, and dangling-call
cleanup. Extracted from core.Agent to keep it focused on orchestration.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from providers.base import LLMProvider

# How many recent messages to keep in context (system + last N)
MAX_CONTEXT_MESSAGES = 50
# Tool messages older than this many exchanges get compacted to single-line notes
TOOL_COMPACT_AFTER = 20
# Maximum characters per tool result (longer results are truncated)
MAX_TOOL_RESULT_CHARS = 4000


def count_tokens(messages: list[dict], model: str = "") -> int:
    """Calculate token count using tiktoken if available, falling back to estimation."""
    try:
        import tiktoken
        try:
            clean_model = model.split("/")[-1] if "/" in model else model
            encoding = tiktoken.encoding_for_model(clean_model)
        except Exception:
            encoding = tiktoken.get_encoding("cl100k_base")

        num_tokens = 0
        for message in messages:
            num_tokens += 4
            for key, value in message.items():
                if isinstance(value, str):
                    num_tokens += len(encoding.encode(value))
                elif isinstance(value, list):
                    for part in value:
                        if isinstance(part, dict) and part.get("type") == "text":
                            num_tokens += len(encoding.encode(part.get("text", "")))
                elif key == "tool_calls" and isinstance(value, list):
                    for tc in value:
                        num_tokens += len(encoding.encode(tc.get("name", "")))
                        args = tc.get("arguments", {})
                        if isinstance(args, dict):
                            num_tokens += len(encoding.encode(json.dumps(args)))
                        elif isinstance(args, str):
                            num_tokens += len(encoding.encode(args))
            num_tokens += 2
        return num_tokens
    except Exception:
        # Fallback approximation: 1 token ~= 4 characters
        total_chars = 0
        for message in messages:
            for key, value in message.items():
                if isinstance(value, str):
                    total_chars += len(value)
                elif isinstance(value, list):
                    for part in value:
                        if isinstance(part, dict) and part.get("type") == "text":
                            total_chars += len(part.get("text", ""))
                elif key == "tool_calls" and isinstance(value, list):
                    for tc in value:
                        total_chars += len(tc.get("name", ""))
                        args = tc.get("arguments", {})
                        if isinstance(args, dict):
                            total_chars += len(json.dumps(args))
                        elif isinstance(args, str):
                            total_chars += len(args)
        return total_chars // 4


def group_into_blocks(messages: list[dict]) -> list[list[dict]]:
    """Group messages into atomic blocks (e.g. user message, or assistant call + all its tool results).

    Ensures that a tool call and its results are never separated.
    """
    blocks: list[list[dict]] = []
    current_block: list[dict] = []
    
    in_tool_block = False
    pending_tool_ids: set[str] = set()
    
    for msg in messages:
        role = msg.get("role")
        
        if role == "system":
            if current_block:
                blocks.append(current_block)
                current_block = []
            blocks.append([msg])
            continue
            
        if role == "user":
            if current_block:
                blocks.append(current_block)
            current_block = [msg]
            in_tool_block = False
            pending_tool_ids = set()
            
        elif role == "assistant":
            if current_block:
                blocks.append(current_block)
            current_block = [msg]
            tool_calls = msg.get("tool_calls")
            if tool_calls:
                in_tool_block = True
                pending_tool_ids = {tc.get("id", tc.get("name", "")) for tc in tool_calls}
            else:
                in_tool_block = False
                pending_tool_ids = set()
                
        elif role == "tool":
            tool_call_id = msg.get("tool_call_id", msg.get("name", ""))
            if in_tool_block and tool_call_id in pending_tool_ids:
                current_block.append(msg)
                pending_tool_ids.discard(tool_call_id)
                if not pending_tool_ids:
                    in_tool_block = False
            else:
                if current_block:
                    blocks.append(current_block)
                current_block = [msg]
                in_tool_block = False
                pending_tool_ids = set()
        else:
            if current_block:
                blocks.append(current_block)
            current_block = [msg]
            
    if current_block:
        blocks.append(current_block)
        
    return blocks


def get_safe_window(messages: list[dict], max_messages: int) -> list[dict]:
    """Slices messages to keep at most max_messages while keeping tool blocks intact."""
    system_msgs = [m for m in messages if m.get("role") == "system"]
    non_system = [m for m in messages if m.get("role") != "system"]
    
    blocks = group_into_blocks(non_system)
    
    kept_messages: list[dict] = []
    total_count = 0
    
    for block in reversed(blocks):
        if total_count + len(block) <= max_messages:
            kept_messages = block + kept_messages
            total_count += len(block)
        else:
            if not kept_messages:
                kept_messages = block
            break
            
    return system_msgs + kept_messages


class ContextWindow:
    """Manages the agent message list and context window constraints.

    Responsibilities:
    - Compact old tool call/result pairs to save tokens
    - Summarize overflow messages into a rolling summary
    - Trim the window for each LLM call
    - Remove dangling tool calls (no matching response)
    """

    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider
        self.messages: list[dict] = []
        self.summary: str = ""  # rolling summary of old overflow

    def _get_context_limit(self) -> int:
        """Determine token limit for the active provider/model."""
        provider_name = self._provider.name.lower() if hasattr(self._provider, "name") else ""
        model_name = getattr(self._provider, "model", "").lower() if hasattr(self._provider, "model") else ""

        limits = {
            "deepseek": 64_000,
            "openai": 128_000,
            "anthropic": 200_000,
            "gemini": 1_000_000,
            "ollama": 32_000,
            "groq": 128_000,
            "openrouter": 128_000,
            "codex": 128_000,
            "google-oauth": 1_000_000,
        }

        if "gpt-3.5" in model_name:
            return 16_000
        if "gpt-4" in model_name or "gpt-4o" in model_name:
            return 128_000
        if "claude" in model_name:
            return 200_000
        if "gemini" in model_name:
            return 1_000_000

        return limits.get(provider_name, 32_000)

    # ── Dangling call cleanup ─────────────────────────────────────────────────

    def drop_dangling_tool_calls(self) -> int:
        """Remove assistant+tool_calls entries that have no matching tool responses.

        Returns the number of messages removed. Used to recover from API 400 errors.
        """
        result_ids: set[str] = {
            m.get("tool_call_id", "")
            for m in self.messages
            if m.get("role") == "tool"
        }
        removed = 0
        clean: list[dict] = []
        skip_ids: set[str] = set()
        for m in self.messages:
            if m.get("role") == "assistant" and m.get("tool_calls"):
                missing = [
                    tc for tc in m["tool_calls"]
                    if tc.get("id", tc.get("name", "")) not in result_ids
                ]
                if missing:
                    for tc in m["tool_calls"]:
                        skip_ids.add(tc.get("id", tc.get("name", "")))
                    removed += 1
                    continue
            if m.get("role") == "tool" and m.get("tool_call_id", "") in skip_ids:
                removed += 1
                continue
            clean.append(m)
        self.messages = clean
        return removed

    # ── Compaction ────────────────────────────────────────────────────────────

    def _compact_tool_messages(self, messages: list[dict]) -> list[dict]:
        """Replace old tool message pairs with single compact notes, preserving blocks."""
        non_system = [m for m in messages if m.get("role") != "system"]
        system_msgs = [m for m in messages if m.get("role") == "system"]

        if len(non_system) <= TOOL_COMPACT_AFTER:
            return messages

        blocks = group_into_blocks(non_system)
        
        recent_blocks: list[list[dict]] = []
        old_blocks: list[list[dict]] = []
        total_recent_count = 0
        
        for block in reversed(blocks):
            if total_recent_count + len(block) <= TOOL_COMPACT_AFTER:
                recent_blocks.insert(0, block)
                total_recent_count += len(block)
            else:
                if not recent_blocks:
                    recent_blocks.insert(0, block)
                    total_recent_count += len(block)
                else:
                    old_blocks.insert(0, block)
        
        if not old_blocks:
            return messages
            
        old_msgs: list[dict] = []
        for b in old_blocks:
            old_msgs.extend(b)
            
        recent_msgs: list[dict] = []
        for b in recent_blocks:
            recent_msgs.extend(b)

        log_lines: list[str] = []
        skip_ids: set[str] = set()
        for m in old_msgs:
            role = m.get("role", "")
            if role == "user":
                content = m.get("content", "")
                if isinstance(content, list):
                    content = " ".join(
                        p.get("text", "") for p in content
                        if isinstance(p, dict) and p.get("type") == "text"
                    )
                if content:
                    log_lines.append(f"USER: {str(content)[:200]}")
            elif role == "assistant":
                content = m.get("content") or ""
                tool_calls = m.get("tool_calls") or []
                if tool_calls:
                    names = ", ".join(tc.get("name", "?") for tc in tool_calls)
                    for tc in tool_calls:
                        skip_ids.add(tc.get("id", tc.get("name", "")))
                    if content:
                        log_lines.append(
                            f"ASSISTANT: {str(content)[:120]} [called: {names}]"
                        )
                    else:
                        log_lines.append(f"ASSISTANT called: {names}")
                elif content:
                    log_lines.append(f"ASSISTANT: {str(content)[:200]}")
            elif role == "tool":
                result = str(m.get("content", ""))[:150]
                name = m.get("name", "tool")
                log_lines.append(f"  ↳ {name}: {result}")

        if log_lines:
            compact_msg = {
                "role": "user",
                "content": "[Earlier conversation summary]\n" + "\n".join(log_lines),
            }
            return system_msgs + [compact_msg] + recent_msgs
        return system_msgs + recent_msgs

    # ── Rolling summary ───────────────────────────────────────────────────────

    def maybe_build_rolling_summary(self) -> None:
        """Summarize older overflow messages when token capacity or message limit is exceeded."""
        limit = self._get_context_limit()
        model_name = getattr(self._provider, "model", "")
        total_tokens = count_tokens(self.messages, model=model_name)

        system = [m for m in self.messages if m.get("role") == "system"]
        rest = [m for m in self.messages if m.get("role") != "system"]

        # Trigger summary if tokens exceed 90% of model limit or message count exceeds MAX_CONTEXT_MESSAGES
        if total_tokens < 0.9 * limit and len(rest) <= MAX_CONTEXT_MESSAGES:
            return

        blocks = group_into_blocks(rest)
        
        # Keep last 5 blocks intact, summarize the rest
        keep_blocks_count = min(5, len(blocks))
        if len(blocks) <= keep_blocks_count:
            return

        overflow_blocks = blocks[:-keep_blocks_count]
        keep_blocks = blocks[-keep_blocks_count:]

        overflow: list[dict] = []
        for b in overflow_blocks:
            overflow.extend(b)

        keep: list[dict] = []
        for b in keep_blocks:
            keep.extend(b)

        lines = []
        for m in overflow:
            role = m.get("role", "")
            content = m.get("content") or ""
            if isinstance(content, list):
                content = " ".join(p.get("text", "") for p in content if isinstance(p, dict))
            if role in ("user", "assistant") and content:
                lines.append(f"{role.upper()}: {str(content)[:300]}")
            elif role == "tool":
                lines.append(f"TOOL ({m.get('name', 'tool')}): {str(m.get('content', ''))[:100]}")

        if not lines:
            self.messages = system + keep
            return

        snippet = "\n".join(lines)
        prompt_content = (
            "Summarize the key facts, decisions, and outcomes from this "
            "conversation excerpt in 3-5 bullet points. Be very concise. "
            "Focus on: what was asked, what was done, key values/names/paths "
            "mentioned.\n\n"
        )
        if self.summary:
            prompt_content += f"Previous rolling summary:\n{self.summary}\n\nNew conversation excerpt to append/update:\n"
        prompt_content += snippet

        try:
            resp = self._provider.chat(
                [
                    {"role": "system", "content": "You are a concise summarizer."},
                    {
                        "role": "user",
                        "content": prompt_content,
                    },
                ],
                tools=None,
            )
            summary_text = (resp.get("content") or "").strip()
            if summary_text:
                self.summary = summary_text
        except Exception:
            self.summary = (self.summary + "\n" if self.summary else "") + "\n".join(lines[-5:])

        self.messages = system + keep

    # ── Trimming ──────────────────────────────────────────────────────────────

    def trim(self, provider_supports_vision: bool = False) -> list[dict]:
        """Return a trimmed, normalized window of messages for an LLM call."""
        window = get_safe_window(self.messages, MAX_CONTEXT_MESSAGES)

        # Pass 0: compact old tool pairs
        window = self._compact_tool_messages(window)

        # Pass 0.5: truncate long tool results to save tokens
        for m in window:
            if m.get("role") == "tool" and isinstance(m.get("content"), str):
                if len(m["content"]) > MAX_TOOL_RESULT_CHARS:
                    m["content"] = (
                        m["content"][:MAX_TOOL_RESULT_CHARS]
                        + f"\n\n[... truncated — {len(m['content'])} chars total]"
                    )

        # Pass 1: remove orphan tool messages (no preceding assistant call)
        valid_call_ids: set[str] = set()
        for m in window:
            if m.get("role") == "assistant" and m.get("tool_calls"):
                for tc in m["tool_calls"]:
                    valid_call_ids.add(tc.get("id", tc.get("name", "")))
        window = [
            m for m in window
            if not (
                m.get("role") == "tool"
                and m.get("tool_call_id", "") not in valid_call_ids
            )
        ]

        # Pass 2: remove dangling assistant+tool_calls
        result_ids: set[str] = {
            m.get("tool_call_id", "") for m in window if m.get("role") == "tool"
        }
        skip_ids: set[str] = set()
        clean: list[dict] = []
        for m in window:
            if m.get("role") == "assistant" and m.get("tool_calls"):
                missing = [
                    tc for tc in m["tool_calls"]
                    if tc.get("id", tc.get("name", "")) not in result_ids
                ]
                if missing:
                    for tc in m["tool_calls"]:
                        skip_ids.add(tc.get("id", tc.get("name", "")))
                    continue
            if m.get("role") == "tool" and m.get("tool_call_id", "") in skip_ids:
                continue
            clean.append(m)

        # Pass 2.5: repair message sequence (stray tools & consecutive users)
        clean = self._repair_message_sequence(clean)

        # Pass 3: normalize to provider API format
        normalized = []
        for m in clean:
            if m.get("role") == "assistant" and m.get("tool_calls"):
                api_tool_calls = []
                for tc in m["tool_calls"]:
                    if "function" in tc:
                        api_tool_calls.append(
                            {"type": "function", **tc} if "type" not in tc else tc
                        )
                    else:
                        args = tc.get("arguments", {})
                        api_tool_calls.append({
                            "id": tc.get("id", tc.get("name", "")),
                            "type": "function",
                            "function": {
                                "name": tc.get("name", ""),
                                "arguments": (
                                    json.dumps(args) if isinstance(args, dict) else str(args)
                                ),
                            },
                        })
                m = {**m, "tool_calls": api_tool_calls}
                if "content" not in m:
                    m = {**m, "content": None}
            elif m.get("role") == "tool":
                m = {**m, "content": str(m.get("content", ""))}
            elif m.get("role") == "assistant" and "content" not in m:
                m = {**m, "content": ""}
            normalized.append(m)

        # Pass 4: flatten vision content for non-vision providers
        if not provider_supports_vision:
            from providers.base import LLMProvider as _LLMProvider
            normalized = _LLMProvider._flatten_messages_for_text(normalized)

        return normalized

    def _repair_message_sequence(self, messages: list[dict]) -> list[dict]:
        """Collapse malformed role-alternation left in the window.

        Repairs:
        1. Stray tool messages without preceding assistant tool_calls -> dropped.
        2. Consecutive user messages -> merged.
        """
        if not messages:
            return messages

        # Pass 1: drop stray tool messages that don't follow a known assistant tool_call_id
        known_tool_ids = set()
        filtered = []
        for msg in messages:
            if not isinstance(msg, dict):
                filtered.append(msg)
                continue
            role = msg.get("role")
            if role == "assistant":
                known_tool_ids = set()
                for tc in (msg.get("tool_calls") or []):
                    tc_id = tc.get("id") if isinstance(tc, dict) else None
                    if tc_id:
                        known_tool_ids.add(tc_id)
                filtered.append(msg)
            elif role == "tool":
                tc_id = msg.get("tool_call_id")
                if tc_id and tc_id in known_tool_ids:
                    filtered.append(msg)
            else:
                if role == "user":
                    known_tool_ids = set()
                filtered.append(msg)

        # Pass 2: merge consecutive user messages
        merged = []
        for msg in filtered:
            if (
                merged
                and isinstance(msg, dict)
                and msg.get("role") == "user"
                and isinstance(merged[-1], dict)
                and merged[-1].get("role") == "user"
            ):
                prev = merged[-1]
                prev_content = prev.get("content", "")
                new_content = msg.get("content", "")
                if isinstance(prev_content, str) and isinstance(new_content, str):
                    prev["content"] = (
                        (prev_content + "\n\n" + new_content)
                        if prev_content and new_content
                        else (prev_content or new_content)
                    )
                    continue
            merged.append(msg)

        return merged
