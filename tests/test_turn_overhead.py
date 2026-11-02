"""One turn stops paying for work it already did (K-10).

The YAML config was re-parsed every round, the skill auto-enable side effect lived
inside the tool selector, and the router's LLM answer was never reused. The parsed
file is now cached on its stat key, the side effect runs once per turn, rounds reuse
the resolved tool list, and repeated messages reuse the routing decision.
"""
import logging
import os
import sys
import threading
from types import SimpleNamespace

import pytest
import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import core as core_module
from core import Agent, ToolLoopGuardrail, _select_tools, _tool_name
from router import IntentRouter
from tools import registry
from utils.tool_resolution_cache import ToolResolutionCache


@pytest.fixture
def config_file(tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"
    monkeypatch.setattr(config, "CONFIG_PATH", path)
    config.clear_config_cache()
    yield path
    config.clear_config_cache()


def _tool(name: str) -> dict:
    return dict(core_module._TOOL_BY_NAME[name])


def _names(tools) -> list[str]:
    return [_tool_name(t) for t in tools]


def _bare_agent() -> Agent:
    """Agent with only the state _resolve_available_tools touches."""
    agent = Agent.__new__(Agent)
    agent.cfg = {}
    agent.messages = []
    agent._session_tool_order = []
    agent._sent_tool_names = set()
    return agent


def _counting_select(monkeypatch, names=("read_file", "web_search")) -> list:
    calls: list = []

    def _select(user_input, *a, **k):
        calls.append(user_input)
        return [_tool(n) for n in names]

    monkeypatch.setattr(core_module, "_select_tools", _select)
    return calls


# ── config cache ────────────────────────────────────────────────────────────

def test_unchanged_file_is_served_from_the_cache(config_file):
    config_file.write_text("language: tr\nemail:\n  username: a\n", encoding="utf-8")
    first = config.load_config()
    assert config.config_cache_info()["misses"] == 1
    second = config.load_config()

    assert first == second
    assert first is not second
    assert config.config_cache_info()["hits"] >= 1


def test_mutating_a_returned_config_does_not_reach_the_cache(config_file):
    config_file.write_text("email:\n  username: a\nlist_key: [1]\n", encoding="utf-8")
    first = config.load_config()
    first["email"]["username"] = "corrupted"
    first["list_key"].append(2)

    second = config.load_config()
    assert second["email"]["username"] == "a"
    assert second["list_key"] == [1]


def test_merge_and_env_overrides_still_apply_on_every_hit(config_file, monkeypatch):
    config_file.write_text("ui:\n  default: tui\n", encoding="utf-8")
    config.load_config()
    monkeypatch.setenv("TELEGRAM_TOKEN", "from-env")
    cfg = config.load_config()

    assert config.config_cache_info()["hits"] == 1
    assert cfg["messaging"]["telegram"]["token"] == "from-env"
    assert cfg["ui"] == {"default": "tui", "refresh_interval_ms": 1500}


def test_rewritten_file_is_picked_up(config_file):
    config_file.write_text("language: tr\n", encoding="utf-8")
    assert config.load_config()["language"] == "tr"
    config_file.write_text("language: de\nmodel: longer-content\n", encoding="utf-8")

    cfg = config.load_config()
    assert cfg["language"] == "de"
    assert cfg["model"] == "longer-content"


def test_cache_is_keyed_on_the_path(tmp_path, config_file, monkeypatch):
    config_file.write_text("language: tr\n", encoding="utf-8")
    config.load_config()
    other = tmp_path / "other.yaml"
    other.write_text("language: de\n", encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG_PATH", other)
    assert config.load_config()["language"] == "de"


def test_broken_file_keeps_its_recovery_path_and_is_not_cached(config_file, capsys):
    config_file.write_text("language: [unclosed\n", encoding="utf-8")
    cfg = config.load_config()

    assert "Failed to load config.yaml" in capsys.readouterr().out
    assert cfg["language"] == "en"
    assert (config_file.parent / "config.yaml.broken").exists()

    # The failure is reported again, not served from the cache.
    assert config.load_config()["language"] == "en"
    assert "Failed to load config.yaml" in capsys.readouterr().out
    assert config.config_cache_info()["hits"] == 0

    config_file.write_text("language: tr\n", encoding="utf-8")
    assert config.load_config()["language"] == "tr"


def test_save_invalidates_even_when_stat_cannot_see_the_write(config_file):
    config_file.write_text("language: tr\n", encoding="utf-8")
    cfg = config.load_config()
    before = config_file.stat()

    cfg["language"] = "de"
    config.save_config(cfg)
    # A coarse mtime and an equal-size payload: only the invalidation can help.
    os.utime(config_file, ns=(before.st_atime_ns, before.st_mtime_ns))

    assert config.load_config()["language"] == "de"


def test_permissions_are_hardened_when_the_file_is_reread(config_file):
    config_file.write_text("language: tr\n", encoding="utf-8")
    config_file.chmod(0o644)
    config.load_config()
    assert config_file.stat().st_mode & 0o777 == 0o600


def test_router_section_has_a_default(config_file):
    assert config.load_config()["router"]["cache_size"] == 128


# ── registry generation ─────────────────────────────────────────────────────

def _stub_plugin_manager(monkeypatch, load_all_plugins):
    # skills/plugin_manager.py does not exist in the repo, so it is stubbed whole.
    stub = SimpleNamespace(load_all_plugins=load_all_plugins)
    monkeypatch.setitem(sys.modules, "skills.plugin_manager", stub)


@pytest.fixture
def offline_registry(config_file, monkeypatch):
    _stub_plugin_manager(monkeypatch, lambda *a, **k: None)
    monkeypatch.setattr("skills.mcp_skill.load_dynamic_mcp_tools", lambda: ([], {}))


def test_generation_tracks_rebuilds_only(offline_registry, caplog):
    start = registry.registry_generation()
    registry.rebuild_registry(force=True)
    rebuilt = registry.registry_generation()
    assert rebuilt > start

    registry.register_plugin_tools([], {})
    registered = registry.registry_generation()
    assert registered > rebuilt

    registry.rebuild_registry()
    assert registry.registry_generation() == registered
    assert not caplog.records, "a clean rebuild must not warn"


def test_plugin_and_mcp_failures_are_visible_but_not_fatal(config_file, monkeypatch, caplog):
    def _boom(*a, **k):
        raise RuntimeError("server down")

    _stub_plugin_manager(monkeypatch, _boom)
    monkeypatch.setattr("skills.mcp_skill.load_dynamic_mcp_tools", _boom)
    start = registry.registry_generation()

    with caplog.at_level(logging.WARNING, logger="tools.registry"):
        registry.rebuild_registry(force=True)

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 2
    assert all(r.exc_info for r in warnings)
    assert registry.ALL_TOOLS, "the registry still fails open"
    assert registry.registry_generation() > start


# ── pure selector ───────────────────────────────────────────────────────────

def test_select_tools_has_no_side_effects(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(config, "load_config", lambda: calls.append("load") or {})
    monkeypatch.setattr(config, "save_config", lambda cfg: calls.append("save"))
    monkeypatch.setattr(registry, "rebuild_registry", lambda force=False: calls.append("rebuild"))

    selected = _select_tools("mail this please", [{"role": "user", "content": "hi"}],
                             router_groups={"email"})

    assert calls == []
    assert "send_email" in _names(selected)


# ── one-time skill enable ───────────────────────────────────────────────────

@pytest.fixture
def enable_recorder(config_file, monkeypatch):
    config_file.write_text(yaml.safe_dump({"disabled_skills": ["email_skill", "finance"]}),
                           encoding="utf-8")
    calls = {"save": 0, "rebuild": []}
    real_save = config.save_config

    def _save(cfg):
        calls["save"] += 1
        real_save(cfg)

    monkeypatch.setattr(config, "save_config", _save)
    monkeypatch.setattr(registry, "rebuild_registry", lambda force=False: calls["rebuild"].append(force))
    return calls


def test_enable_runs_once_and_removes_only_what_is_needed(enable_recorder):
    assert core_module._enable_skill_groups({"email"}) is True
    assert config.load_config()["disabled_skills"] == ["finance"]
    assert enable_recorder == {"save": 1, "rebuild": [True]}

    assert core_module._enable_skill_groups({"email"}) is False
    assert enable_recorder == {"save": 1, "rebuild": [True]}


def test_enable_saves_once_for_several_skills(enable_recorder):
    assert core_module._enable_skill_groups({"email", "finance"}) is True
    assert config.load_config()["disabled_skills"] == []
    assert enable_recorder == {"save": 1, "rebuild": [True]}


@pytest.mark.parametrize("groups", [None, set(), {"file"}, {"cron"}])
def test_enable_is_a_noop_without_a_disabled_match(enable_recorder, groups):
    assert core_module._enable_skill_groups(groups) is False
    assert enable_recorder == {"save": 0, "rebuild": []}


def test_enable_logs_a_failing_rebuild(enable_recorder, monkeypatch, caplog):
    def _boom(force=False):
        raise RuntimeError("rebuild failed")

    monkeypatch.setattr(registry, "rebuild_registry", _boom)
    with caplog.at_level(logging.WARNING, logger="core"):
        assert core_module._enable_skill_groups({"email"}) is False
    assert any(r.levelno == logging.WARNING and r.exc_info for r in caplog.records)


# ── ToolResolutionCache ─────────────────────────────────────────────────────

KEY = (1, {"email"}, "hello", ("read_file",))


def test_cache_hit_returns_an_equal_copy():
    cache = ToolResolutionCache()
    stored = [{"name": "a"}]
    cache.put(*KEY, stored)
    stored.append({"name": "late"})

    hit = cache.get(*KEY)
    assert hit == [{"name": "a"}]
    hit.append({"name": "b"})
    assert cache.get(*KEY) == [{"name": "a"}]
    assert len(cache) == 1


def test_an_empty_selection_is_a_hit_not_a_miss():
    cache = ToolResolutionCache()
    cache.put(*KEY, [])
    assert cache.get(*KEY) == []


@pytest.mark.parametrize("key", [
    (2, {"email"}, "hello", ("read_file",)),
    (1, {"cron"}, "hello", ("read_file",)),
    (1, None, "hello", ("read_file",)),
    (1, {"email"}, "other", ("read_file",)),
    (1, {"email"}, "hello", ("read_file", "web_search")),
])
def test_any_changed_key_field_misses(key):
    cache = ToolResolutionCache()
    cache.put(*KEY, [{"name": "a"}])
    assert cache.get(*key) is None


def test_context_is_part_of_the_key():
    cache = ToolResolutionCache()
    cache.put(*KEY, [{"name": "a"}], context="one")
    assert cache.get(*KEY) is None
    assert cache.get(*KEY, context="two") is None
    assert cache.get(*KEY, context="one") == [{"name": "a"}]


def test_max_entries_evicts_the_oldest_and_clear_empties():
    cache = ToolResolutionCache(max_entries=2)
    for i in range(3):
        cache.put(i, None, "x", (), [{"name": str(i)}])

    assert len(cache) == 2
    assert cache.get(0, None, "x", ()) is None
    assert cache.get(2, None, "x", ()) == [{"name": "2"}]

    cache.clear()
    assert len(cache) == 0


# ── router decision cache ───────────────────────────────────────────────────

# Trips _is_hybrid_query, so the heuristic stands aside and the LLM path runs.
LLM_MESSAGE = "search for cats"


class _FakeProvider:
    def __init__(self, content='{"tool_groups": ["email"]}'):
        self.content = content
        self.calls = 0

    def chat(self, messages, tools=None):
        self.calls += 1
        if isinstance(self.content, Exception):
            raise self.content
        return {"content": self.content}


def test_identical_messages_cost_one_llm_call():
    provider = _FakeProvider()
    router = IntentRouter(provider)

    first = router.classify(LLM_MESSAGE)
    second = router.classify(LLM_MESSAGE)

    assert provider.calls == 1
    assert first == second
    assert first.tool_groups == ["email"]

    router.classify(LLM_MESSAGE + " else")
    assert provider.calls == 2


def test_key_ignores_case_and_whitespace():
    provider = _FakeProvider()
    router = IntentRouter(provider)
    router.classify(LLM_MESSAGE)
    router.classify("  " + LLM_MESSAGE.upper().replace(" ", "\n  "))
    assert provider.calls == 1


@pytest.mark.parametrize("size", [0, -1])
def test_cache_size_zero_or_less_disables_the_cache(size):
    provider = _FakeProvider()
    router = IntentRouter(provider, cache_size=size)
    router.classify(LLM_MESSAGE)
    router.classify(LLM_MESSAGE)
    assert provider.calls == 2


def test_cache_is_bounded_and_evicts_the_oldest():
    provider = _FakeProvider()
    router = IntentRouter(provider, cache_size=2)
    for suffix in ("a", "b", "c"):
        router.classify(f"{LLM_MESSAGE} {suffix}")
    assert provider.calls == 3

    router.classify(f"{LLM_MESSAGE} c")
    assert provider.calls == 3
    router.classify(f"{LLM_MESSAGE} a")
    assert provider.calls == 4


def test_a_failed_llm_call_is_not_remembered():
    provider = _FakeProvider(RuntimeError("503"))
    router = IntentRouter(provider)
    assert router.classify(LLM_MESSAGE).tool_groups == []

    provider.content = '{"tool_groups": ["email"]}'
    assert router.classify(LLM_MESSAGE).tool_groups == ["email"]
    assert provider.calls == 2


def test_a_returned_decision_cannot_corrupt_the_cache():
    router = IntentRouter(_FakeProvider())
    router.classify(LLM_MESSAGE).tool_groups.append("miss")
    router.classify(LLM_MESSAGE).tool_groups.append("hit")
    assert router.classify(LLM_MESSAGE).tool_groups == ["email"]


def test_heuristic_decisions_never_reach_the_llm_or_the_cache():
    provider = _FakeProvider()
    router = IntentRouter(provider)
    router.classify("send an email to my boss")
    router.classify("send an email to my boss")
    assert provider.calls == 0
    assert router._cache == {}


def test_a_broken_cache_falls_through_to_a_fresh_classify():
    provider = _FakeProvider()
    router = IntentRouter(provider)
    router._cache = None
    assert router.classify(LLM_MESSAGE).tool_groups == ["email"]
    assert provider.calls == 1


# ── per-round memo ──────────────────────────────────────────────────────────

def test_rounds_reuse_the_selection(monkeypatch):
    calls = _counting_select(monkeypatch)
    agent = _bare_agent()
    for _ in range(10):
        agent._resolve_available_tools("hello", {"file"}, True)
    assert len(calls) == 1


def test_registry_change_reselects(monkeypatch):
    calls = _counting_select(monkeypatch)
    agent = _bare_agent()
    agent._resolve_available_tools("hello", None, True)
    agent._resolve_available_tools("hello", None, True)
    assert len(calls) == 1

    monkeypatch.setattr(registry, "_REGISTRY_GENERATION", registry.registry_generation() + 1)
    agent._resolve_available_tools("hello", None, True)
    assert len(calls) == 2


def test_changed_previous_tools_reselect(monkeypatch):
    calls = _counting_select(monkeypatch)
    agent = _bare_agent()
    agent._resolve_available_tools("hello", None, True)
    agent._resolve_available_tools("hello", None, True, previous_tools=[_tool("vision_analyze")])
    assert len(calls) == 2


def test_a_hit_returns_a_private_equal_list(monkeypatch):
    _counting_select(monkeypatch)
    agent = _bare_agent()
    first = agent._resolve_available_tools("hello", None, True)
    second = agent._resolve_available_tools("hello", None, True)
    assert first == second

    second.append(_tool("vision_analyze"))
    assert agent._resolve_available_tools("hello", None, True) == first


def test_a_hit_still_publishes_the_visible_names(monkeypatch):
    """tool_search excludes these names, so a hit must keep them current."""
    _counting_select(monkeypatch)
    agent = _bare_agent()
    first = agent._resolve_available_tools("hello", None, True)
    agent._sent_tool_names = set()
    agent._resolve_available_tools("hello", None, True)
    assert agent._sent_tool_names == set(_names(first))


def test_a_tool_called_mid_turn_still_widens_the_next_round():
    """The selector keeps a called tool's whole group, whatever the key's fields say."""
    agent = _bare_agent()
    before = _names(agent._resolve_available_tools("hello", None, True))
    assert "read_emails" not in before

    agent.messages.append({"role": "assistant", "content": "",
                           "tool_calls": [{"name": "send_email", "arguments": "{}"}]})
    after = _names(agent._resolve_available_tools("hello", None, True))

    fresh = _bare_agent()
    fresh.messages = agent.messages
    assert "read_emails" in after
    assert set(after) == set(before) | set(_names(fresh._resolve_available_tools("hello", None, True)))


def test_is_local_is_part_of_the_memo(monkeypatch):
    calls = _counting_select(monkeypatch)
    agent = _bare_agent()
    agent._resolve_available_tools("hello", None, True)
    agent._resolve_available_tools("hello", None, False)
    assert len(calls) == 2


def test_a_memoized_narrow_selection_cannot_undo_stickiness(monkeypatch):
    """Narrow, wide, narrow: the third call must not replay the first array."""
    monkeypatch.setattr(core_module, "_select_tools", lambda text, *a, **k: [
        _tool(n) for n in (["read_file", "send_email"] if "@" in text else ["read_file"])
    ])
    agent = _bare_agent()
    agent._resolve_available_tools("hello", None, True)
    wide = agent._resolve_available_tools("a@b.com", None, True)
    assert agent._resolve_available_tools("hello", None, True) == wide


def test_reset_clears_the_memo(monkeypatch):
    monkeypatch.setattr("config.save_config", lambda cfg: None)
    calls = _counting_select(monkeypatch)
    agent = _bare_agent()
    agent.channel = "cli"
    agent._ctx = SimpleNamespace(summary="", messages=[])
    agent.auto_save = lambda *a, **k: "saved"
    agent._session_progress = 0.0
    agent._resolve_available_tools("hello", None, True)
    assert len(agent._tool_resolution_cache) == 1

    Agent.reset(agent)
    assert len(agent._tool_resolution_cache) == 0
    assert len(calls) == 1


# ── end to end: the real loop ───────────────────────────────────────────────

class _LoopProvider:
    name = "ollama"
    supports_vision = False
    supports_thinking = False
    _model = "fake-model"

    def __init__(self, rounds):
        self._rounds = list(rounds)

    def stream_chat(self, messages, tools=None, cancel_event=None):
        if self._rounds:
            yield from self._rounds.pop(0)


def _loop_agent(rounds, router=None):
    agent = _bare_agent()
    agent.provider = _LoopProvider(rounds)
    agent.channel = "cli"
    agent.messages = [{"role": "system", "content": "test"}]
    agent._cancel = threading.Event()
    agent._busy = False
    agent._router = router
    agent._guardrail = ToolLoopGuardrail()
    agent.permission_callback = None
    agent.tool_progress_callback = None
    agent._activated_tools = set()
    agent._pre_fetch_links = lambda user_input: iter(())
    agent._refresh_memory_context = lambda *a, **k: None
    agent._execute_tool = lambda name, args: f"ran {name}"
    return agent


def test_each_turn_enables_skills_once_and_starts_a_clean_memo(monkeypatch):
    enabled: list = []
    monkeypatch.setattr(core_module, "_enable_skill_groups",
                        lambda groups: enabled.append(groups) or True)
    calls = _counting_select(monkeypatch)
    tool_round = [{"__tool_chunk__": True, "index": 0, "id": "c1",
                   "name": "read_file", "args_chunk": '{"path": "a"}'}]
    agent = _loop_agent(
        [tool_round, ["done"], ["done"]],
        router=IntentRouter(_FakeProvider()),
    )

    list(agent._run_conversation_loop(LLM_MESSAGE))
    assert len(enabled) == 1, "exactly one auto-enable per turn, not one per round"
    assert "email" in enabled[0], "the routed group must reach the auto-enable step"
    assert "research" in enabled[0] and "web" in enabled[0], (
        "keyword/history groups must reach it too, not just the router output"
    )

    selections = len(calls)
    list(agent._run_conversation_loop(LLM_MESSAGE))
    assert len(enabled) == 2
    assert len(calls) > selections, "the second turn must not reuse the first turn's memo"


def test_auto_enable_sees_keyword_groups_without_a_router(monkeypatch):
    """The old selector enabled skills from keyword groups too; keep that contract."""
    enabled: list = []
    monkeypatch.setattr(core_module, "_enable_skill_groups",
                        lambda groups: enabled.append(set(groups)) or False)
    _counting_select(monkeypatch)
    agent = _loop_agent([["done"]], router=None)

    list(agent._run_conversation_loop("email a@b.com about the report"))
    assert enabled, "the turn must still run the auto-enable step"
    assert "email" in enabled[0]


def test_a_failing_link_prefetch_is_logged_and_survived(monkeypatch, caplog):
    _counting_select(monkeypatch)
    agent = _loop_agent([["done"]])

    def _boom(user_input):
        raise RuntimeError("fetch failed")
        yield

    agent._pre_fetch_links = _boom
    with caplog.at_level(logging.DEBUG, logger="core"):
        events = list(agent._run_conversation_loop("hello"))

    assert any(r.exc_info for r in caplog.records if r.levelno == logging.DEBUG)
    assert any(e.get("type") == "text" or e.get("token") for e in events)
