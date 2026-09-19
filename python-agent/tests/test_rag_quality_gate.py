import importlib.util
from pathlib import Path
from types import SimpleNamespace


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
    report = evaluate_rag._real_llm_scores(
        "答案是什么？",
        [{"content": "证据说明答案是 A。", "metadata": {}}],
    )

    assert report["faithfulness"] == 0.9
    assert report["answer_relevance"] == 0.8
    assert [call[1]["max_tokens"] for call in calls] == [400, 200]
