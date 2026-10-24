import threading

from config import default_config
from core import Agent, ToolLoopGuardrail
from providers.base import LLMProvider
from utils.key_health import (
    AUTH,
    BILLING,
    RATE_LIMIT,
    KeyPool,
    KeyRotationPolicy,
    should_rotate,
)


class _FakeClock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def test_policy_defaults_overrides_and_garbage():
    defaults = KeyRotationPolicy()
    assert KeyRotationPolicy.from_config(None) == defaults
    assert KeyRotationPolicy.from_config({}) == defaults
    assert KeyRotationPolicy.from_config({"key_rotation": "nope"}) == defaults
    assert KeyRotationPolicy.from_config({
        "billing_cooldown_seconds": 42,
        "rate_limit_cooldown_seconds": 7,
        "default_cooldown_seconds": 11,
        "auth_disables_key": False,
    }) == KeyRotationPolicy(False, 42, 7, 11)

    policy = KeyRotationPolicy.from_config({
        "billing_cooldown_seconds": -1,
        "rate_limit_cooldown_seconds": "10",
        "default_cooldown_seconds": True,
        "auth_disables_key": "false",
    })
    assert policy == defaults
    assert KeyRotationPolicy.from_config({"key_rotation": None}) == defaults


def test_default_config_exposes_key_rotation_policy():
    assert default_config()["key_rotation"] == {
        "auth_disables_key": True,
        "billing_cooldown_seconds": 1800,
        "rate_limit_cooldown_seconds": 60,
        "default_cooldown_seconds": 300,
    }


def test_pool_selection_is_sticky():
    pool = KeyPool(["sk-key-alpha-1234567890", "sk-key-beta-1234567890"])

    assert [pool.current_key for _ in range(5)] == ["sk-key-alpha-1234567890"] * 5
    assert pool.current_index == 0


def test_auth_failure_disables_key_permanently():
    clock = _FakeClock()
    pool = KeyPool(["sk-key-alpha-1234567890", "sk-key-beta-1234567890"], clock=clock)

    assert pool.rotate(AUTH) is True
    assert pool.current_key == "sk-key-beta-1234567890"
    assert pool.snapshot()[0]["status"] == "disabled"
    clock.advance(3600)
    assert pool.available_count() == 1
    assert pool.snapshot()[0]["status"] == "disabled"


def test_billing_cooldown_expires_at_deadline():
    clock = _FakeClock()
    policy = KeyRotationPolicy(billing_cooldown_seconds=30)
    pool = KeyPool(["sk-key-alpha-1234567890", "sk-key-beta-1234567890"], policy, clock)

    pool.mark_failure(BILLING, status_code=402)
    assert pool.snapshot()[0]["cooldown_until"] == 1030.0
    clock.advance(29)
    assert pool.available_count() == 1
    assert pool.snapshot()[0]["status"] == "cooldown"
    clock.advance(1)
    assert pool.available_count() == 2
    assert pool.snapshot()[0]["status"] == "ok"


def test_rate_limit_cooldown_and_success_clear_failure_state():
    clock = _FakeClock()
    policy = KeyRotationPolicy(rate_limit_cooldown_seconds=5)
    pool = KeyPool(["sk-key-alpha-1234567890", "sk-key-beta-1234567890"], policy, clock)

    pool.mark_failure(RATE_LIMIT, status_code=429)
    assert pool.snapshot()[0]["cooldown_until"] == 1005.0
    assert pool.snapshot()[0]["failures"] == 1
    pool.mark_success()
    assert pool.snapshot()[0]["status"] == "ok"
    assert pool.snapshot()[0]["failures"] == 0
    assert pool.snapshot()[0]["last_reason"] == ""
    assert pool.snapshot()[0]["cooldown_until"] is None


def test_rotation_with_all_keys_disabled_preserves_index_and_masks_keys():
    keys = ["sk-very-secret-alpha-123456", "sk-very-secret-beta-654321"]
    pool = KeyPool(keys)
    pool.mark_failure(AUTH, index=0)
    pool.mark_failure(AUTH, index=1)
    index = pool.current_index

    assert pool.rotate(AUTH) is False
    assert pool.current_index == index
    assert all(entry["status"] == "disabled" for entry in pool.snapshot())
    assert all(key not in repr(pool.snapshot()) for key in keys)

    pool.mark_success(index=0)
    assert pool.snapshot()[0]["status"] == "disabled"


def test_should_rotate_is_limited_to_known_reasons_and_attempt_cap():
    assert should_rotate(AUTH, 0, 5) is True
    assert should_rotate("rate_limit", 4, 5) is True
    assert should_rotate(BILLING, 0, 5) is True
    assert should_rotate("unknown", 0, 5) is False
    assert should_rotate(AUTH, 5, 5) is False


class _KeyTestProvider(LLMProvider):
    def chat(self, messages, tools=None, stream=False):
        return {}

    def stream_chat(self, messages, tools=None, cancel_event=None):
        yield from ()

    def list_models(self):
        return []

    @property
    def name(self):
        return "key-test"


def test_provider_key_rotation_uses_health_pool():
    provider = _KeyTestProvider()
    provider._cfg = {"api_key": ["sk-test-key-alpha-123456", "sk-test-key-beta-654321"]}

    assert provider._get_api_key(provider._cfg) == "sk-test-key-alpha-123456"
    assert provider.rotate_key(AUTH) is True
    assert provider._get_api_key(provider._cfg) == "sk-test-key-beta-654321"
    assert provider.rotate_key(AUTH) is False
    assert provider._get_api_key(provider._cfg) == "sk-test-key-beta-654321"
    assert [entry["status"] for entry in provider.key_health()] == ["disabled", "disabled"]


class _AuthRetryProvider:
    name = "fake"
    supports_vision = False
    supports_thinking = False
    _model = "fake-model"

    def __init__(self):
        self.calls = 0
        self.rotate_reasons = []

    def stream_chat(self, messages, tools=None, cancel_event=None):
        self.calls += 1
        if self.calls == 1:
            error = Exception("invalid api key")
            error.status_code = 401
            raise error
        yield "Recovered text"

    def rotate_key(self, reason=""):
        self.rotate_reasons.append(reason)
        return True


class _NoUsableKeysProvider(_AuthRetryProvider):
    def stream_chat(self, messages, tools=None, cancel_event=None):
        error = Exception("provider says invalid api key")
        error.status_code = 401
        raise error

    def rotate_key(self, reason=""):
        self.rotate_reasons.append(reason)
        return False

    def key_health(self):
        return [{"status": "disabled"}, {"status": "disabled"}]


def _agent_for_provider(provider):
    agent = Agent.__new__(Agent)
    agent.provider = provider
    agent.cfg = {}
    agent.messages = [{"role": "system", "content": "test"}]
    agent._cancel = threading.Event()
    agent._busy = False
    agent._router = None
    agent._guardrail = ToolLoopGuardrail()
    agent.permission_callback = None
    agent.tool_progress_callback = None
    agent._pre_fetch_links = lambda user_input: iter(())
    agent._refresh_memory_context = lambda *a, **k: None
    agent._resolve_available_tools = lambda *a, **k: []
    agent._execute_tool = lambda name, args: ""
    return agent


def test_stream_loop_retries_after_auth_failure():
    agent = _agent_for_provider(_AuthRetryProvider())

    events = list(agent._run_conversation_loop("test request"))

    assert agent.provider.calls == 2
    assert agent.provider.rotate_reasons == [AUTH]
    assert "".join(
        event["token"] for event in events if event.get("type") == "text"
    ).endswith("Recovered text")


def test_all_disabled_keys_preserve_provider_error_and_warn_once(caplog):
    agent = _agent_for_provider(_NoUsableKeysProvider())

    events = list(agent._run_conversation_loop("test request"))

    errors = [event for event in events if event.get("type") == "error"]
    assert len(errors) == 1
    assert errors[0]["message"] == "provider says invalid api key"
    assert caplog.text.count(
        "No usable API key left: all configured keys are disabled."
    ) == 1
