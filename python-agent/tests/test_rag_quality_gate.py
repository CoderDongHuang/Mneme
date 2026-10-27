import importlib.util
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "evaluate_rag.py"
SPEC = importlib.util.spec_from_file_location("evaluate_rag", SCRIPT)
assert SPEC and SPEC.loader
evaluate_rag = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(evaluate_rag)


def test_quality_gate_reports_all_failed_thresholds():
    failures = evaluate_rag.apply_thresholds(
        {"recall@5": 0.8, "p95_latency_ms": 300},
        {"recall@5": {"min": 0.9}, "p95_latency_ms": {"max": 250}},
    )
    assert failures == [
        "recall@5=0.8 is below 0.9",
        "p95_latency_ms=300.0 exceeds 250",
    ]


def test_quality_gate_rejects_missing_metrics():
    assert evaluate_rag.apply_thresholds({}, {"mrr": {"min": 0.8}}) == [
        "missing metric: mrr"
    ]


def test_quality_gate_rejects_nonfinite_and_nonnumeric_metrics():
    for value in (float("nan"), float("inf"), True, None, "1.0"):
        assert evaluate_rag.apply_thresholds({"mrr": value}, {"mrr": {"min": 0.8}}) == [
            "invalid numeric metric: mrr"]


def test_real_llm_gate_requires_completed_evaluation():
    assert evaluate_rag.apply_real_llm_thresholds(
        {"real_llm_evaluation": {"status": "disabled"}},
        {"faithfulness": {"min": 0.7}},
    ) == ["real_llm_evaluation was not completed"]


def test_real_llm_gate_applies_nested_thresholds():
    failures = evaluate_rag.apply_real_llm_thresholds(
        {
            "real_llm_evaluation": {
                "status": "completed",
                "faithfulness": 0.6,
                "answer_relevance": 0.9,
            }
        },
        {"faithfulness": {"min": 0.7}, "answer_relevance": {"min": 0.7}},
    )
    assert failures == ["real_llm_evaluation.faithfulness=0.6 is below 0.7"]


def test_real_llm_scoring_limits_both_model_responses(monkeypatch):
    calls = []
    responses = iter([
        SimpleNamespace(content="根据证据，答案是 A [1]。"),
        SimpleNamespace(content='{"faithfulness":0.9,"answer_relevance":0.8,"reason":"grounded"}'),
    ])

    def invoke(messages, **kwargs):
        calls.append((messages, kwargs))
        return next(responses)

    monkeypatch.setattr(evaluate_rag.llm, "invoke", invoke)
    monkeypatch.setattr(evaluate_rag.llm, "ainvoke", AsyncMock(return_value=SimpleNamespace(content='{"checks":[{"id":0,"supported":true,"quotes":[{"citation":1,"text":"答案是 A"}]}]}')))
    report = asyncio.run(evaluate_rag._real_llm_scores(
        "答案是什么？",
        [{"content": "证据说明答案是 A。", "metadata": {}}],
    ))

    assert report["faithfulness"] == 0.9
    assert report["answer_relevance"] == 0.8
    assert [call[1]["max_tokens"] for call in calls] == [400, 200]
    assert "任务规则" in calls[0][0][0][1]


@pytest.mark.parametrize("value", [float("nan"), float("inf"), True, None, "1.0", -0.1, 1.1])
def test_real_judge_rejects_invalid_scores(monkeypatch, value):
    responses = iter([SimpleNamespace(content="答案[1]。"), SimpleNamespace(content=json.dumps(
        {"faithfulness": value, "answer_relevance": 1}))])
    monkeypatch.setattr(evaluate_rag.llm, "invoke", lambda *args, **kwargs: next(responses))
    monkeypatch.setattr(evaluate_rag, "verify_evidence_answer", AsyncMock(return_value="答案[1]。"))
    with pytest.raises(ValueError, match="Invalid judge score"):
        asyncio.run(evaluate_rag._real_llm_scores("答案？", [{"content": "答案是 A。"}]))


def test_evaluation_shares_one_loop_across_samples(monkeypatch, tmp_path):
    loops = []

    async def verify(state, answer):
        loops.append(asyncio.get_running_loop())
        return answer

    fixture = tmp_path / "synthetic.txt"
    fixture.write_text("答案是 A。", encoding="utf-8")
    dataset = tmp_path / "cases.json"
    dataset.write_text(json.dumps([{"question": "答案？", "fixture": str(fixture),
                                   "expected_source": "synthetic.txt", "expected_terms": ["A"]}] * 3), encoding="utf-8")
    monkeypatch.setattr(evaluate_rag, "ingest_document", lambda *args, **kwargs: None)
    monkeypatch.setattr(evaluate_rag.vector_store, "delete_collection", lambda *args: None)
    monkeypatch.setattr(evaluate_rag, "retrieve", lambda *args: [
        {"content": "答案是 A。", "metadata": {"source": "synthetic.txt"}}])
    responses = iter([SimpleNamespace(content="答案是 A[1]。"), SimpleNamespace(
        content='{"faithfulness":1,"answer_relevance":1}')] * 3)
    monkeypatch.setattr(evaluate_rag.llm, "invoke", lambda *args, **kwargs: next(responses))
    monkeypatch.setattr(type(evaluate_rag.llm), "configured", property(lambda self: True))
    monkeypatch.setattr(evaluate_rag, "verify_evidence_answer", verify)
    report = evaluate_rag.evaluate(dataset, 5, False, llm_sample_size=3,
                                 input_cost_per_million=0.3, output_cost_per_million=0.6,
                                 max_estimated_cost=0.08)
    assert report["real_llm_evaluation"]["samples"] == 3
    assert len(loops) == 3 and all(loop is loops[0] for loop in loops)


def test_real_model_sampling_includes_unanswerable_cases_at_end():
    cases = [{"answerable": True}] * 10 + [{"answerable": False}] * 2
    selected = evaluate_rag.select_model_sample_indices(cases, 8)
    assert len(selected) == 8 and {10, 11} <= selected
    assert evaluate_rag.select_model_sample_indices(cases, 0) == set()


def test_answer_points_are_scored_semantically_and_keep_reasons(monkeypatch):
    calls = []
    responses = iter([SimpleNamespace(content="甲方案于五月开放。"), SimpleNamespace(content=json.dumps({
        "faithfulness": 1, "answer_relevance": 1, "answer_points": [
            {"index": 0, "matched": True, "reason": "回答用五月表述了证据中的开放月份"},
            {"index": 1, "matched": False, "reason": "遗漏另一份资料中的冲突日期"}]}))])
    def invoke(messages, **kwargs):
        calls.append(messages)
        return next(responses)
    monkeypatch.setattr(evaluate_rag.llm, "invoke", invoke)
    monkeypatch.setattr(evaluate_rag, "verify_evidence_answer", AsyncMock(return_value="甲方案于五月开放。"))
    report = asyncio.run(evaluate_rag._real_llm_scores("开放时间？", [], True, ["5月开放", "指出日期冲突"]))
    assert report["answer_point_coverage"] == 0.5
    assert report["answer_points"][1]["reason"]
    assert "5月开放" in calls[1][1][1]


def test_missing_or_duplicate_point_judgments_fail_closed(monkeypatch):
    responses = iter([SimpleNamespace(content="答案"), SimpleNamespace(content=json.dumps({
        "faithfulness": 1, "answer_relevance": 1, "answer_points": []}))])
    monkeypatch.setattr(evaluate_rag.llm, "invoke", lambda *args, **kwargs: next(responses))
    monkeypatch.setattr(evaluate_rag, "verify_evidence_answer", AsyncMock(return_value="答案"))
    with pytest.raises(ValueError, match="answer point"):
        asyncio.run(evaluate_rag._real_llm_scores("问题", [], True, ["必须覆盖的要点"]))
