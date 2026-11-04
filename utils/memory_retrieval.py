"""Lexical relevance helpers for shared-memory recall (K-17).

Pure functions only: no database access and no imports from ``skills/``.
The caller fetches candidate rows (FTS5 or LIKE) and uses these helpers to
turn a natural-language message into safe search terms and to rank rows by
how well they match those terms.
"""
from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

# Short English + Turkish filler list. Kept deliberately small: anything not
# listed here is treated as a content word.
STOPWORDS: frozenset[str] = frozenset({
    # English
    "the", "and", "for", "are", "was", "were", "you", "your", "yours", "our",
    "what", "which", "who", "whom", "whose", "when", "where", "why", "how",
    "this", "that", "these", "those", "with", "from", "into", "about", "have",
    "has", "had", "does", "did", "can", "could", "would", "should", "will",
    "shall", "may", "might", "must", "not", "but", "any", "all", "some", "there",
    "their", "them", "they", "then", "than", "its", "mine", "please",
    "tell", "know", "just", "also", "very", "too", "out", "get", "let",
    # Turkish
    "bir", "için", "icin", "benim", "bana", "beni", "sen", "senin", "nasıl",
    "nasil", "neden", "niye", "nedir", "hangi", "şey", "sey", "gibi", "daha",
    "çok", "cok", "ama", "veya", "ile", "olan", "olarak", "kadar", "şu", "şimdi",
    "simdi", "lütfen", "lutfen", "var", "yok", "değil", "degil", "mı", "mi",
    "mu", "mü", "ne", "ve", "bu", "da", "de",
})

_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)
_SAFE_TERM_RE = re.compile(r"^[^\W_]+$", re.UNICODE)

_KEY_WEIGHT = 6.0
_TAG_WEIGHT = 3.0
_VALUE_WEIGHT = 2.0
_VALUE_MAX_HITS = 3
_PREFIX_MIN_LEN = 4


def _tokens(text: Any) -> list[str]:
    return _TOKEN_RE.findall(str(text or "").lower())


def tokenize_query(text: str | None, max_terms: int = 12) -> list[str]:
    """Turn free text into deduplicated, lowercase content terms."""
    if not text:
        return []
    terms: list[str] = []
    seen: set[str] = set()
    for token in _tokens(text):
        if len(token) < 3 or token in STOPWORDS or token in seen:
            continue
        seen.add(token)
        terms.append(token)
        if len(terms) >= max_terms:
            break
    return terms


def _safe_terms(terms: Sequence[str]) -> list[str]:
    return [t for t in terms if isinstance(t, str) and _SAFE_TERM_RE.match(t)]


def build_fts_query(terms: Sequence[str]) -> str:
    """Build an FTS5 MATCH expression: quoted prefix terms joined by OR.

    Every term is re-validated as a single word, so raw user text never
    reaches MATCH. Returns "" when no safe term remains.
    """
    return " OR ".join(f'"{t}"*' for t in _safe_terms(terms))


def build_like_patterns(terms: Sequence[str]) -> list[str]:
    """LIKE patterns for the non-FTS fallback (one per term)."""
    return [f"%{t}%" for t in _safe_terms(terms)]


def _matches(term: str, token: str) -> bool:
    return term == token or (len(term) >= _PREFIX_MIN_LEN and token.startswith(term))


def score_memory(key: str, value: str, tags: str, terms: Sequence[str]) -> float:
    """Deterministic lexical score; 0.0 means no term matched."""
    key_tokens = _tokens(key)
    tag_tokens = _tokens(tags)
    value_tokens = _tokens(value)
    score = 0.0
    for term in terms:
        if any(_matches(term, tok) for tok in key_tokens):
            score += _KEY_WEIGHT
        if any(_matches(term, tok) for tok in tag_tokens):
            score += _TAG_WEIGHT
        hits = sum(1 for tok in value_tokens if _matches(term, tok))
        score += _VALUE_WEIGHT * min(hits, _VALUE_MAX_HITS)
    return score


def rank_memories(rows: Sequence[Mapping[str, Any]], terms: Sequence[str], limit: int) -> list:
    """Rank rows by score, then recency, then key; drop non-matching rows.

    With no terms the input order is kept (the caller decides about recency).
    Rows with a duplicate key are collapsed to the first occurrence.
    """
    limit = max(0, int(limit))
    unique: list[Mapping[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        key = str(row["key"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    if not terms:
        return unique[:limit]
    scored = []
    for row in unique:
        score = score_memory(row["key"], row["value"], row["tags"], terms)
        if score > 0:
            scored.append((score, row))
    scored.sort(key=lambda item: (-item[0], -float(item[1]["updated_at"] or 0), str(item[1]["key"])))
    return [row for _, row in scored[:limit]]


def _positive_int(value: Any, default: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return default
    return value


@dataclass(frozen=True)
class RecallPolicy:
    enabled: bool = True
    limit: int = 8
    max_terms: int = 12

    @classmethod
    def from_config(cls, cfg: Any) -> RecallPolicy:
        """Read ``cfg["memory"]["recall"]``; bad or missing values use defaults."""
        default = cls()
        try:
            section = cfg.get("memory", {}).get("recall", {})
            if not isinstance(section, Mapping):
                return default
            enabled = section.get("enabled", default.enabled)
            return cls(
                enabled=enabled if isinstance(enabled, bool) else default.enabled,
                limit=_positive_int(section.get("limit"), default.limit),
                max_terms=_positive_int(section.get("max_terms"), default.max_terms),
            )
        except (AttributeError, TypeError):
            return default
