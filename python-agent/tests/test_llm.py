import asyncio
from types import SimpleNamespace

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
