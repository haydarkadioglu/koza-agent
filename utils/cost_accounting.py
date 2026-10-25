"""Usage and cost accounting for koza turns (K-27).

K-15 taught the loop to read provider usage, but nothing multiplied tokens by
a price.  This module turns a canonical usage dict (``normalize_usage`` in
``utils/token_accounting.py``) into an estimated USD amount.

Prices come from, in order: user overrides (``cost_tracking.prices`` in
``config.yaml``), an OpenRouter-style catalog lookup supplied by the caller,
and a small built-in fallback table.  The built-in numbers are approximate
public list prices, not authoritative billing data; override them with
``cost_tracking.prices`` when they matter.  A model with no known price
yields ``None`` — "cost unknown" — never ``0``.

Stdlib only and import-safe: nothing here touches the network.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

logger = logging.getLogger(__name__)

_PER_MTOK = 1_000_000

# OpenRouter-style per-token pricing keys, as normalised by
# ``utils.model_metadata._extract_pricing``, plus the raw aliases it accepts.
_PRICING_ALIASES: dict[str, tuple[str, ...]] = {
    "prompt": ("prompt", "input", "input_cost_per_token", "prompt_token_cost"),
    "completion": ("completion", "output", "output_cost_per_token", "completion_token_cost"),
    "cache_read": ("cache_read", "cached_prompt", "input_cache_read", "cache_read_cost_per_token"),
    "cache_write": ("cache_write", "cache_creation", "input_cache_write", "cache_write_cost_per_token"),
}


def _as_float(value: Any) -> float:
    """Parse a non-negative finite float; anything else reads as 0.0."""
    if isinstance(value, bool):
        return 0.0
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(number) or number < 0:
        return 0.0
    return number


def _as_count(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


@dataclass(frozen=True)
class ModelPrice:
    """Price of one model in USD per 1M tokens."""

    input_per_mtok: float = 0.0
    output_per_mtok: float = 0.0
    cache_read_per_mtok: float = 0.0
    cache_write_per_mtok: float = 0.0
    source: str = "builtin"

    @classmethod
    def from_per_token(cls, mapping: Mapping[str, Any], source: str = "catalog") -> ModelPrice:
        """Build from an OpenRouter-style dict of per-token price strings."""
        normalized: dict[str, Any] = {}
        if isinstance(mapping, Mapping):
            normalized = {str(key).lower(): value for key, value in mapping.items()}

        def pick(target: str) -> float:
            for alias in _PRICING_ALIASES[target]:
                if alias in normalized and normalized[alias] not in (None, ""):
                    return _as_float(normalized[alias]) * _PER_MTOK
            return 0.0

        return cls(
            input_per_mtok=pick("prompt"),
            output_per_mtok=pick("completion"),
            cache_read_per_mtok=pick("cache_read"),
            cache_write_per_mtok=pick("cache_write"),
            source=source,
        )

    @property
    def is_free(self) -> bool:
        return not (self.input_per_mtok or self.output_per_mtok
                    or self.cache_read_per_mtok or self.cache_write_per_mtok)

    def cost(self, usage: Mapping[str, int]) -> float:
        """USD cost of one canonical usage dict (see ``estimate_cost``)."""
        usage = usage if isinstance(usage, Mapping) else {}
        prompt = _as_count(usage.get("prompt_tokens"))
        completion = _as_count(usage.get("completion_tokens"))
        cache_read = _as_count(usage.get("cache_read_tokens"))
        cache_write = _as_count(usage.get("cache_write_tokens"))
        reasoning = _as_count(usage.get("reasoning_tokens"))

        read_rate = self.cache_read_per_mtok or self.input_per_mtok
        write_rate = self.cache_write_per_mtok or self.input_per_mtok
        billable_prompt = max(0, prompt - cache_read)
        output = completion if completion else reasoning
        total = (
            billable_prompt * self.input_per_mtok
            + cache_read * read_rate
            + cache_write * write_rate
            + output * self.output_per_mtok
        )
        return total / _PER_MTOK


def _price_from_override(entry: Any) -> ModelPrice | None:
    """Parse one ``cost_tracking.prices`` entry (USD per 1M tokens)."""
    if isinstance(entry, ModelPrice):
        return entry
    if isinstance(entry, (list, tuple)):
        if len(entry) != 2:
            return None
        values = []
        for item in entry:
            if isinstance(item, bool) or not isinstance(item, (int, float, str)):
                return None
            try:
                number = float(item)
            except ValueError:
                return None
            if not math.isfinite(number) or number < 0:
                return None
            values.append(number)
        return ModelPrice(input_per_mtok=values[0], output_per_mtok=values[1], source="override")
    if isinstance(entry, Mapping):
        def pick(*keys: str) -> float | None:
            for key in keys:
                if key in entry and entry[key] not in (None, ""):
                    return _as_float(entry[key])
            return None

        input_price = pick("input", "input_per_mtok", "prompt")
        output_price = pick("output", "output_per_mtok", "completion")
        if input_price is None and output_price is None:
            return None
        return ModelPrice(
            input_per_mtok=input_price or 0.0,
            output_per_mtok=output_price or 0.0,
            cache_read_per_mtok=pick("cache_read", "cache_read_per_mtok") or 0.0,
            cache_write_per_mtok=pick("cache_write", "cache_write_per_mtok") or 0.0,
            source="override",
        )
    return None


@dataclass(frozen=True)
class CostPolicy:
    """Settings from the ``cost_tracking`` section of ``config.yaml``."""

    enabled: bool = True
    currency: str = "USD"
    overrides: Mapping[str, ModelPrice] = field(default_factory=lambda: MappingProxyType({}))

    @classmethod
    def from_config(cls, cfg: Any) -> CostPolicy:
        """Read ``cfg["cost_tracking"]``; fail-open to the default policy."""
        try:
            section = cfg.get("cost_tracking") if isinstance(cfg, Mapping) else None
            if not isinstance(section, Mapping):
                return cls()
            enabled = section.get("enabled", True)
            enabled = enabled if isinstance(enabled, bool) else True
            currency = section.get("currency")
            currency = currency.strip().upper() if isinstance(currency, str) and currency.strip() else "USD"
            overrides: dict[str, ModelPrice] = {}
            prices = section.get("prices")
            if isinstance(prices, Mapping):
                for model, entry in prices.items():
                    if not isinstance(model, str) or not model.strip():
                        continue
                    price = _price_from_override(entry)
                    if price is None:
                        logger.debug("cost_tracking: skipping unparseable price for %r", model)
                        continue
                    overrides[model.strip()] = price
            return cls(enabled=enabled, currency=currency, overrides=MappingProxyType(overrides))
        except Exception:  # accounting config must never break startup
            logger.debug("cost_tracking: malformed section, using defaults", exc_info=True)
            return cls()


def _b(input_price: float, output_price: float, cache_read: float = 0.0, cache_write: float = 0.0) -> ModelPrice:
    return ModelPrice(input_price, output_price, cache_read, cache_write, source="builtin")


# APPROXIMATE public list prices, USD per 1M tokens (input, output, cache read,
# cache write).  These are a convenience fallback, not authoritative billing
# data, and drift as vendors change pricing — override any of them with
# ``cost_tracking.prices`` in config.yaml.  Keys are matched as substrings of
# the model id (longest key wins), so order does not matter.
BUILTIN_PRICES: Mapping[str, ModelPrice] = MappingProxyType({
    # OpenAI
    "gpt-4o": _b(2.50, 10.00, 1.25),
    "gpt-4o-mini": _b(0.15, 0.60, 0.075),
    "gpt-4.1": _b(2.00, 8.00, 0.50),
    "gpt-4.1-mini": _b(0.40, 1.60, 0.10),
    "gpt-4.1-nano": _b(0.10, 0.40, 0.025),
    "o3": _b(2.00, 8.00, 0.50),
    "o4-mini": _b(1.10, 4.40, 0.275),
    # Anthropic
    "claude-opus-4": _b(15.00, 75.00, 1.50, 18.75),
    "claude-sonnet-4": _b(3.00, 15.00, 0.30, 3.75),
    "claude-3-5-haiku": _b(0.80, 4.00, 0.08, 1.00),
    "claude-haiku-3.5": _b(0.80, 4.00, 0.08, 1.00),
    # DeepSeek
    "deepseek-chat": _b(0.27, 1.10, 0.07),
    "deepseek-reasoner": _b(0.55, 2.19, 0.14),
    # Google
    "gemini-2.0-flash": _b(0.10, 0.40, 0.025),
    "gemini-2.5-pro": _b(1.25, 10.00, 0.31),
    "gemini-2.5-flash": _b(0.30, 2.50, 0.075),
    # Moonshot
    "kimi-k2": _b(0.60, 2.50, 0.15),
    # xAI
    "grok-3": _b(3.00, 15.00, 0.75),
    "grok-3-mini": _b(0.30, 0.50, 0.075),
})


def _norm(text: str) -> str:
    return str(text).strip().lower().replace("_", "-").replace(".", "-")


def _match(model: str, table: Mapping[str, ModelPrice]) -> ModelPrice | None:
    """Exact id, then bare id, then the longest key contained in the id."""
    if not model or not table:
        return None
    if model in table:
        return table[model]
    bare = model.rsplit("/", 1)[-1]
    if bare in table:
        return table[bare]
    normalized = {_norm(key): price for key, price in table.items()}
    norm_model, norm_bare = _norm(model), _norm(bare)
    for candidate in (norm_model, norm_bare):
        if candidate in normalized:
            return normalized[candidate]
    best_key = ""
    for key in normalized:
        if key and len(key) > len(best_key) and _contains_at_boundary(norm_model, key):
            best_key = key
    return normalized[best_key] if best_key else None


def _contains_at_boundary(text: str, key: str) -> bool:
    """``key`` occurs in ``text`` starting at the beginning of an id segment.

    Keeps short keys such as ``o3`` from matching inside unrelated ids.
    """
    start = text.find(key)
    while start != -1:
        if start == 0 or text[start - 1] in "-/:":
            return True
        start = text.find(key, start + 1)
    return False


def _from_catalog(model: str, catalog: Callable[[str], Any]) -> ModelPrice | None:
    try:
        found = catalog(model)
    except Exception:  # a catalog failure must stay invisible
        logger.debug("cost_tracking: catalog lookup failed for %s", model, exc_info=True)
        return None
    if not isinstance(found, Mapping) or not found:
        return None
    pricing = found.get("pricing") if isinstance(found.get("pricing"), Mapping) else found
    price = ModelPrice.from_per_token(pricing, source="catalog")
    # An empty or all-zero catalog entry is not a usable price; let the
    # built-in table (or "cost unknown") answer instead of reporting $0.
    return None if price.is_free else price


def resolve_price(
    model: str,
    policy: CostPolicy,
    catalog: Callable[[str], Any] | None = None,
) -> ModelPrice | None:
    """Best known price for ``model``: override, then catalog, then built-in."""
    model = str(model or "").strip()
    if not model:
        return None
    overrides = getattr(policy, "overrides", None) or {}
    price = _match(model, overrides)
    if price is not None:
        return price
    if catalog is not None:
        price = _from_catalog(model, catalog)
        if price is not None:
            return price
    return _match(model, BUILTIN_PRICES)


def estimate_cost(usage: Mapping[str, int], price: ModelPrice | None) -> float | None:
    """Estimated cost of one response in the price's currency, or ``None``.

    Billing rule: in the OpenAI-compatible shape ``prompt_tokens`` already
    *includes* cached tokens, so ``max(0, prompt_tokens - cache_read_tokens)``
    is charged at ``input_per_mtok`` and ``cache_read_tokens`` at
    ``cache_read_per_mtok`` (the input price when no cache-read rate is
    known).  ``cache_write_tokens`` are charged at ``cache_write_per_mtok``
    (again falling back to the input price) and ``completion_tokens`` at
    ``output_per_mtok``.  ``reasoning_tokens`` are already part of
    ``completion_tokens``, so they are billed only when
    ``completion_tokens == 0``.

    Returns ``None`` when the price is unknown or the usage has no tokens.
    """
    if price is None or not isinstance(usage, Mapping):
        return None
    keys = ("prompt_tokens", "completion_tokens", "cache_read_tokens",
            "cache_write_tokens", "reasoning_tokens")
    if not any(_as_count(usage.get(key)) for key in keys):
        return None
    return price.cost(usage)


_CURRENCY_SYMBOLS = {"USD": "$", "EUR": "€", "GBP": "£"}


def format_cost(amount: float | None, currency: str = "USD") -> str:
    """``"$0.0123"`` style; ``"<$0.0001"`` for tiny amounts; ``"cost unknown"``."""
    if amount is None:
        return "cost unknown"
    amount = _as_float(amount)
    code = str(currency or "USD").upper()
    symbol = _CURRENCY_SYMBOLS.get(code)
    prefix, suffix = (symbol, "") if symbol else ("", f" {code}")
    if amount == 0:
        return f"{prefix}0.00{suffix}"
    if amount < 0.0001:
        return f"<{prefix}0.0001{suffix}"
    if amount < 1:
        return f"{prefix}{amount:.4f}{suffix}"
    return f"{prefix}{amount:,.2f}{suffix}"


def format_usage_line(usage: Mapping[str, int], price: ModelPrice | None, currency: str = "USD") -> str:
    """One compact line such as ``"2,431 in / 118 out (1,024 cached) · $0.0089"``."""
    usage = usage if isinstance(usage, Mapping) else {}
    prompt = _as_count(usage.get("prompt_tokens"))
    completion = _as_count(usage.get("completion_tokens"))
    cached = _as_count(usage.get("cache_read_tokens"))
    line = f"{prompt:,} in / {completion:,} out"
    if cached:
        line += f" ({cached:,} cached)"
    return f"{line} · {format_cost(estimate_cost(usage, price), currency)}"
