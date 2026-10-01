import asyncio
from types import SimpleNamespace

import pytest

from langchain_core.messages import HumanMessage, SystemMessage

from app.utils import llm as llm_module


def test_deterministic_model_returns_contract_outputs():
    model = llm_module.DeterministicTestLLM()

    intent = model.invoke(
        [SystemMessage(content="只输出 intent 和 confidence JSON"), HumanMessage(content="识别码是什么")]
    )
    distilled = model.invoke([SystemMessage(content="你是一个记忆蒸馏器")])
    answer = model.invoke([HumanMessage(content="星桥计划的核心识别码是什么？")])

    assert intent.content == '{"intent":"qa","confidence":0.99,"extracted_entities":[]}'
    assert distilled.content == "[]"
    assert "QZ-7294" in answer.content
    assert "[1]" in answer.content


def test_deterministic_model_stream_matches_sync_answer():
    model = llm_module.DeterministicTestLLM()
    messages = [HumanMessage(content="星桥计划的核心识别码是什么？")]

    async def collect():
        return [chunk.content async for chunk in model.astream(messages)]

    chunks = asyncio.run(collect())

    assert "".join(chunks) == model.invoke(messages).content


def test_fallback_llm_selects_deterministic_model(monkeypatch):
    monkeypatch.setattr(
        llm_module,
        "settings",
        SimpleNamespace(
            deterministic_test_llm=True,
            deepseek_api_key="",
            dashscope_api_key="",
        ),
    )
    client = llm_module.FallbackLLM()

    selected, using_fallback = client._selected()

    assert client.configured is True
    assert client.status["primary"] == "deterministic-test"
    assert isinstance(selected, llm_module.DeterministicTestLLM)
    assert using_fallback is False


def test_fallback_llm_uses_dashscope_when_primary_key_is_missing(monkeypatch):
    monkeypatch.setattr(
        llm_module,
        "settings",
        SimpleNamespace(
            deterministic_test_llm=False,
            deepseek_api_key="",
            dashscope_api_key="configured",
        ),
    )
    client = llm_module.FallbackLLM()
    fallback = object()
    monkeypatch.setattr(client, "_get_fallback", lambda: fallback)

    selected, using_fallback = client._selected()

    assert client.configured is True
    assert selected is fallback
    assert using_fallback is True


def test_daily_budget_reserves_before_provider_call(monkeypatch):
    monkeypatch.setattr(
        llm_module,
        "settings",
        SimpleNamespace(
            deterministic_test_llm=False,
            deepseek_api_key="configured",
            dashscope_api_key="",
            llm_daily_budget_usd=0.0011,
            llm_primary_input_cost_per_million=1.0,
            llm_primary_output_cost_per_million=1.0,
            llm_default_max_output_tokens=1000,
        ),
    )
    client = llm_module.FallbackLLM()
    client._reserve_budget(["a"], {"max_tokens": 1000}, False)
    assert client.budget_status()["daily_spend_usd"] > 0
    with pytest.raises(RuntimeError, match="成本预算"):
        client._reserve_budget(["a" * 1000], {"max_tokens": 1000}, False)


def test_stream_budget_rejection_clears_active_gauge(monkeypatch):
    monkeypatch.setattr(
        llm_module,
        "settings",
        SimpleNamespace(
            deterministic_test_llm=False,
            deepseek_api_key="configured",
            dashscope_api_key="",
            llm_daily_budget_usd=0.00001,
            llm_primary_input_cost_per_million=1.0,
            llm_primary_output_cost_per_million=1.0,
            llm_default_max_output_tokens=1000,
        ),
    )
    client = llm_module.FallbackLLM()
    monkeypatch.setattr(client, "_selected", lambda: (object(), False))

    async def collect():
        return [chunk async for chunk in client.astream(["hello"])]

    before = llm_module.LLM_ACTIVE._value.get()
    with pytest.raises(RuntimeError, match="成本预算"):
        asyncio.run(collect())
    assert llm_module.LLM_ACTIVE._value.get() == before


def test_budget_uses_shared_counter_when_redis_configured(monkeypatch):
    monkeypatch.setattr(
        llm_module,
        "settings",
        SimpleNamespace(
            deterministic_test_llm=False,
            llm_daily_budget_usd=0.002,
            llm_primary_input_cost_per_million=1.0,
            llm_primary_output_cost_per_million=1.0,
            redis_host="redis",
        ),
    )

    class Counter:
        def __init__(self):
            self.total = 0.0

        def eval(self, _script, _keys, _key, charge, limit):
            if self.total + charge > limit:
                return b"-1"
            self.total += charge
            return str(self.total).encode()

    shared = Counter()
    first = llm_module.FallbackLLM()
    second = llm_module.FallbackLLM()
    first._budget_redis = shared
    second._budget_redis = shared
    first._reserve_budget(["one"], {"max_tokens": 1000}, False)
    with pytest.raises(RuntimeError, match="成本预算"):
        second._reserve_budget(["two"], {"max_tokens": 1000}, False)


def test_budget_status_reads_shared_counter_and_reports_outage(monkeypatch):
    monkeypatch.setattr(llm_module, "settings", SimpleNamespace(
        llm_daily_budget_usd=1.0, redis_host="redis"
    ))
    client = llm_module.FallbackLLM()

    class Shared:
        def get(self, _key):
            return b"0.75"

    client._budget_redis = Shared()
    assert client.budget_status()["remaining_usd"] == 0.25

    class Down:
        def get(self, _key):
            raise ConnectionError("unavailable")

    client._budget_redis = Down()
    assert client.budget_status()["status"] == "unavailable"
    assert client.budget_status()["daily_spend_usd"] is None


@pytest.mark.parametrize("mode", ["sync", "async", "stream"])
def test_budget_output_limit_is_forwarded_to_provider(monkeypatch, mode):
    monkeypatch.setattr(llm_module, "settings", SimpleNamespace(
        deterministic_test_llm=False, llm_daily_budget_usd=1.0,
        llm_primary_input_cost_per_million=1.0,
        llm_primary_output_cost_per_million=1.0,
        llm_default_max_output_tokens=123,
    ))
    received = []

    class Provider:
        def invoke(self, messages, **kwargs):
            received.append(kwargs)
            return "answer"

        async def ainvoke(self, messages, **kwargs):
            return self.invoke(messages, **kwargs)

        async def astream(self, messages, **kwargs):
            yield self.invoke(messages, **kwargs)

    client = llm_module.FallbackLLM()
    monkeypatch.setattr(client, "_selected", lambda: (Provider(), False))
    if mode == "sync":
        assert client.invoke(["hello"]) == "answer"
    elif mode == "async":
        assert asyncio.run(client.ainvoke(["hello"])) == "answer"
    else:
        async def collect():
            return [chunk async for chunk in client.astream(["hello"])]
        assert asyncio.run(collect()) == ["answer"]
    assert received == [{"max_tokens": 123}]


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1])
def test_budget_rejects_invalid_limit(monkeypatch, value):
    monkeypatch.setattr(llm_module, "settings", SimpleNamespace(llm_daily_budget_usd=value))
    with pytest.raises(RuntimeError, match="finite and nonnegative"):
        llm_module.FallbackLLM()._reserve_budget(["hello"], {}, False)


def test_budget_rejects_nonfinite_prices_and_counter(monkeypatch):
    monkeypatch.setattr(llm_module, "settings", SimpleNamespace(
        llm_daily_budget_usd=1.0, llm_primary_input_cost_per_million=float("nan"),
        llm_primary_output_cost_per_million=1.0, redis_host="redis",
    ))
    client = llm_module.FallbackLLM()
    with pytest.raises(RuntimeError):
        client._reserve_budget(["hello"], {}, False)
    llm_module.settings.llm_primary_input_cost_per_million = 1.0

    class InvalidCounter:
        def eval(self, *args):
            return "nan"

        def get(self, *args):
            return "nan"

    client._budget_redis = InvalidCounter()
    with pytest.raises(RuntimeError):
        client._reserve_budget(["hello"], {}, False)
    assert client.budget_status()["status"] == "unavailable"
