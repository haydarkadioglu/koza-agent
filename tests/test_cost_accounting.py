"""Usage and cost accounting in the provider layer (K-27).

K-15 recorded the last request's usage only.  These tests pin the new layer:
prices resolve override → catalog → built-in, a usage dict is priced without
double billing cached or reasoning tokens, the ledger accumulates session
totals, and the agent loop prices every ``__usage__`` event it records.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.test_token_accounting import _make_agent  # noqa: I001 - sys.path bootstrap above
from utils.cost_accounting import (
    BUILTIN_PRICES,
    CostPolicy,
    ModelPrice,
    estimate_cost,
    format_cost,
    format_usage_line,
    resolve_price,
)
from utils.token_accounting import TokenLedger


# ── ModelPrice ────────────────────────────────────────────────────────────────

def test_from_per_token_openrouter_pricing():
    price = ModelPrice.from_per_token({
        "prompt": "0.0000025",
        "completion": "0.00001",
        "cache_read": "0.00000125",
        "request": "0",
    })
    assert price.input_per_mtok == pytest.approx(2.5)
    assert price.output_per_mtok == pytest.approx(10.0)
    assert price.cache_read_per_mtok == pytest.approx(1.25)
    assert price.cache_write_per_mtok == 0.0
    assert price.source == "catalog"


def test_from_per_token_tolerates_missing_and_garbage_values():
    price = ModelPrice.from_per_token({"input": "0.000003", "completion": "n/a"})
    assert price.input_per_mtok == pytest.approx(3.0)
    assert price.output_per_mtok == 0.0
    assert ModelPrice.from_per_token({}).input_per_mtok == 0.0
    assert ModelPrice.from_per_token(None).output_per_mtok == 0.0


# ── estimate_cost ─────────────────────────────────────────────────────────────

_PRICE = ModelPrice(input_per_mtok=2.0, output_per_mtok=8.0, cache_read_per_mtok=0.5, source="override")


def test_estimate_cost_plain_prompt_and_completion():
    usage = {"prompt_tokens": 1_000_000, "completion_tokens": 500_000}
    assert estimate_cost(usage, _PRICE) == pytest.approx(2.0 + 4.0)


def test_estimate_cost_applies_cache_read_discount_without_double_billing():
    # 1M prompt tokens of which 800k were served from cache.
    usage = {"prompt_tokens": 1_000_000, "completion_tokens": 0, "cache_read_tokens": 800_000}
    assert estimate_cost(usage, _PRICE) == pytest.approx(0.2 * 2.0 + 0.8 * 0.5)


def test_estimate_cost_cache_rates_fall_back_to_input_price():
    price = ModelPrice(input_per_mtok=1.0, output_per_mtok=1.0)
    usage = {"prompt_tokens": 1_000_000, "cache_read_tokens": 500_000, "cache_write_tokens": 1_000_000}
    assert estimate_cost(usage, price) == pytest.approx(0.5 + 0.5 + 1.0)


def test_estimate_cost_reasoning_billed_only_when_completion_is_zero():
    assert estimate_cost({"completion_tokens": 0, "reasoning_tokens": 1_000_000}, _PRICE) == pytest.approx(8.0)
    # Reasoning is already inside completion_tokens: not billed twice.
    both = {"completion_tokens": 1_000_000, "reasoning_tokens": 600_000}
    assert estimate_cost(both, _PRICE) == pytest.approx(8.0)


def test_estimate_cost_unknown_price_or_empty_usage_is_none():
    assert estimate_cost({"prompt_tokens": 10}, None) is None
    assert estimate_cost({}, _PRICE) is None


def test_format_cost_and_usage_line():
    assert format_cost(None) == "cost unknown"
    assert format_cost(0.0) == "$0.00"
    assert format_cost(0.00001) == "<$0.0001"
    assert format_cost(0.01234) == "$0.0123"
    assert format_cost(12.3456) == "$12.35"
    line = format_usage_line({"prompt_tokens": 2431, "completion_tokens": 118, "cache_read_tokens": 1024}, _PRICE)
    assert line.startswith("2,431 in / 118 out (1,024 cached) · $")
    assert format_usage_line({}, None) == "0 in / 0 out · cost unknown"


# ── resolve_price ─────────────────────────────────────────────────────────────

def _catalog(entry):
    return lambda model: entry


def test_override_beats_catalog_beats_builtin():
    override = ModelPrice(9.0, 9.0, source="override")
    policy = CostPolicy(overrides={"gpt-4o": override})
    catalog = _catalog({"pricing": {"prompt": "0.000001", "completion": "0.000002"}})

    assert resolve_price("gpt-4o", policy, catalog) is override
    from_catalog = resolve_price("gpt-4o", CostPolicy(), catalog)
    assert from_catalog.source == "catalog"
    assert from_catalog.input_per_mtok == pytest.approx(1.0)
    assert resolve_price("gpt-4o", CostPolicy(), None) is BUILTIN_PRICES["gpt-4o"]


def test_empty_catalog_entry_falls_through_to_builtin():
    price = resolve_price("gpt-4o", CostPolicy(), _catalog({"pricing": {}}))
    assert price.source == "builtin"


def test_provider_prefixed_and_separator_insensitive_matches():
    override = ModelPrice(3.0, 15.0, source="override")
    policy = CostPolicy(overrides={"claude-sonnet-4.5": override})
    assert resolve_price("anthropic/claude-sonnet-4-5", policy) is override
    assert resolve_price("claude_sonnet_4_5-20250929", policy) is override
    # Built-in table: longest key wins and a provider prefix is ignored.
    assert resolve_price("openai/gpt-4o-mini-2024-07-18", CostPolicy()) is BUILTIN_PRICES["gpt-4o-mini"]
    assert resolve_price("deepseek/deepseek-chat", CostPolicy()).source == "builtin"


def test_unknown_model_is_none_and_short_keys_do_not_overmatch():
    assert resolve_price("totally-unknown-model", CostPolicy()) is None
    assert resolve_price("", CostPolicy()) is None
    assert resolve_price("qwen-turbo3", CostPolicy()) is None


def test_raising_catalog_is_swallowed():
    def boom(model):
        raise RuntimeError("network down")

    assert resolve_price("gpt-4o", CostPolicy(), boom).source == "builtin"
    assert resolve_price("mystery", CostPolicy(), boom) is None


# ── CostPolicy.from_config ────────────────────────────────────────────────────

def test_policy_defaults_and_disable():
    default = CostPolicy.from_config({})
    assert default.enabled is True
    assert default.currency == "USD"
    assert dict(default.overrides) == {}
    assert CostPolicy.from_config({"cost_tracking": {"enabled": False}}).enabled is False
    assert CostPolicy.from_config(None).enabled is True
    assert CostPolicy.from_config({"cost_tracking": "yes please"}).enabled is True


def test_policy_parses_all_override_shapes_and_skips_bad_entries():
    policy = CostPolicy.from_config({"cost_tracking": {"prices": {
        "model-a": {"input": 1.0, "output": 2.0, "cache_read": 0.1, "cache_write": 1.25},
        "model-b": {"input_per_mtok": 3, "output_per_mtok": 4},
        "model-c": [5, 6],
        "bad-list": [1, 2, 3],
        "bad-type": "cheap",
        "bad-map": {"colour": "blue"},
        "bad-values": ["x", None],
    }}})
    assert set(policy.overrides) == {"model-a", "model-b", "model-c"}
    a = policy.overrides["model-a"]
    assert (a.input_per_mtok, a.output_per_mtok, a.cache_read_per_mtok, a.cache_write_per_mtok) == (1.0, 2.0, 0.1, 1.25)
    assert policy.overrides["model-b"].output_per_mtok == 4.0
    assert policy.overrides["model-c"].input_per_mtok == 5.0
    assert all(p.source == "override" for p in policy.overrides.values())
    with pytest.raises(TypeError):
        policy.overrides["model-d"] = ModelPrice()  # read-only mapping


# ── TokenLedger session totals ────────────────────────────────────────────────

def test_ledger_accumulates_session_totals_and_cost():
    ledger = TokenLedger()
    ledger.record({"prompt_tokens": 1_000_000, "completion_tokens": 0, "cache_read_tokens": 800_000},
                  model="m", price=_PRICE)
    first = ledger.last_cost
    ledger.record({"prompt_tokens": 500_000, "completion_tokens": 250_000}, model="m", price=_PRICE)

    assert first == pytest.approx(0.8)
    assert ledger.last_cost == pytest.approx(1.0 + 2.0)
    assert ledger.session_prompt_tokens == 1_500_000
    assert ledger.session_completion_tokens == 250_000
    assert ledger.session_total_tokens == 1_750_000
    assert ledger.session_cache_read_tokens == 800_000
    assert ledger.session_requests == 2
    assert ledger.session_priced_requests == 2
    assert ledger.session_cost == pytest.approx(3.8)
    # The K-15 per-response view still reflects only the latest response.
    assert ledger.last_prompt_tokens == 500_000


def test_ledger_unpriced_response_keeps_cost_unknown():
    ledger = TokenLedger()
    ledger.record({"prompt_tokens": 100, "completion_tokens": 10})
    assert ledger.last_cost is None
    assert ledger.session_requests == 1
    assert ledger.usage_report()["cost_known"] is False


def test_ledger_reset_clears_session_totals():
    ledger = TokenLedger()
    ledger.record({"prompt_tokens": 100, "completion_tokens": 10}, price=_PRICE)
    ledger.reset()
    report = ledger.usage_report()
    assert all(value == 0 for value in report["session"].values())
    assert ledger.last_cost is None
    assert report["cost_known"] is False


def test_usage_report_shape_and_summary_compatibility():
    ledger = TokenLedger()
    ledger.record({"prompt_tokens": 100, "completion_tokens": 10}, model="m", price=_PRICE)
    report = ledger.usage_report()
    assert set(report) == {"last", "session", "model", "cost_known"}
    assert set(report["session"]) == {
        "prompt_tokens", "completion_tokens", "total_tokens", "cache_read_tokens",
        "cache_write_tokens", "requests", "cost", "priced_requests",
    }
    assert report["last"]["prompt_tokens"] == 100
    assert report["model"] == "m"
    assert report["cost_known"] is True
    assert set(ledger.summary()) == {"prompt_tokens", "completion_tokens", "total_tokens", "samples", "model"}


# ── agent loop wiring ─────────────────────────────────────────────────────────

def _no_network(monkeypatch):
    import utils.model_metadata as metadata

    monkeypatch.setattr(metadata, "fetch_model_metadata", lambda force_refresh=False: {})
    monkeypatch.setattr(metadata, "cached_model_metadata", dict)


def test_agent_prices_usage_with_configured_override(monkeypatch):
    _no_network(monkeypatch)
    agent = _make_agent([
        ["first", {"__usage__": {"prompt_tokens": 2000, "completion_tokens": 100, "total_tokens": 2100}}],
        ["second", {"__usage__": {"prompt_tokens": 3000, "completion_tokens": 50, "total_tokens": 3050}}],
    ])
    agent.cfg = {"cost_tracking": {"prices": {"fake-model": {"input": 2.0, "output": 8.0}}}}

    list(agent._run_conversation_loop("hello"))
    list(agent._run_conversation_loop("again"))

    report = agent.usage_report()
    assert report["session"]["total_tokens"] == 5150
    assert report["session"]["requests"] == 2
    assert report["session"]["cost"] == pytest.approx((5000 * 2.0 + 150 * 8.0) / 1_000_000)
    assert report["cost_known"] is True
    assert report["model"] == "fake-model"


def test_agent_unknown_model_reports_cost_unknown(monkeypatch):
    _no_network(monkeypatch)
    agent = _make_agent([["x", {"__usage__": {"prompt_tokens": 10, "completion_tokens": 1}}]])
    list(agent._run_conversation_loop("hello"))
    report = agent.usage_report()
    assert report["session"]["total_tokens"] == 11
    assert report["cost_known"] is False


def test_agent_turn_usage_is_logged_once_per_turn(monkeypatch, caplog):
    _no_network(monkeypatch)
    agent = _make_agent([["x", {"__usage__": {"prompt_tokens": 1234, "completion_tokens": 5}}]])
    agent.cfg = {"cost_tracking": {"prices": {"fake-model": [1.0, 1.0]}}}
    with caplog.at_level("DEBUG", logger="core"):
        list(agent._run_conversation_loop("hello"))
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("usage:")]
    assert len(lines) == 1
    assert lines[0].startswith("usage: 1,234 in / 5 out · ~$")
    assert "this turn" in lines[0] and "session" in lines[0]


def test_disabled_policy_skips_pricing(monkeypatch):
    _no_network(monkeypatch)
    agent = _make_agent([["x", {"__usage__": {"prompt_tokens": 10, "completion_tokens": 1}}]])
    agent.cfg = {"cost_tracking": {"enabled": False, "prices": {"fake-model": [1.0, 1.0]}}}
    list(agent._run_conversation_loop("hello"))
    assert agent.usage_report()["cost_known"] is False
