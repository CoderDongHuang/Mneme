import importlib.util
from pathlib import Path
from types import SimpleNamespace

from scripts.quality_policy import CostBudget


SCRIPT = Path(__file__).parents[1] / "scripts" / "evaluate_quiz_quality.py"
SPEC = importlib.util.spec_from_file_location("evaluate_quiz_quality", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_quiz_quality_report_scores_grounded_questions():
    workspace = {
        "quizzes": [{
            "title": "Evidence quiz",
            "questions_json": [{
                "type": "choice",
                "prompt": "What is the retention period?",
                "options": ["12 months", "42 months"],
                "answer": "42 months",
                "evidence": "Archive retention is 42 months.",
                "source": {"document_id": "doc_1", "page": 1},
            }],
        }]
    }
    report = MODULE.deterministic_report(workspace)
    assert report["questions"] == 1
    assert report["structural_validity"] == 1.0
    assert report["evidence_coverage"] == 1.0
    assert report["source_coverage"] == 1.0
    assert report["issues"] == []


def test_quiz_quality_report_exposes_invalid_short_question():
    workspace = {
        "quizzes": [{
            "title": "Broken quiz",
            "questions_json": '[{"type":"short","prompt":"Explain","answer":"A"}]',
        }]
    }
    report = MODULE.deterministic_report(workspace)
    assert report["structural_validity"] == 0.0
    assert {"missing_key_points", "missing_evidence", "missing_source"} == set(
        report["issues"][0]["issues"]
    )


def test_quiz_quality_thresholds_report_failures():
    assert MODULE.apply_thresholds(
        {"grounding": 0.6, "clarity": 0.9},
        {"grounding": {"min": 0.75}, "clarity": {"min": 0.8}},
    ) == ["grounding=0.6 is below 0.75"]


def test_real_quiz_scoring_reserves_budget_and_limits_output(monkeypatch):
    workspace = {
        "quizzes": [{
            "title": "Synthetic",
            "questions_json": [{
                "type": "short",
                "prompt": "解释证据",
                "answer": "证据支持答案",
                "key_points": ["证据"],
                "evidence": "资料中的虚构证据",
                "source": {"document_id": "synthetic"},
            }],
        }]
    }
    calls = []

    def invoke(messages, **kwargs):
        calls.append((messages, kwargs))
        return SimpleNamespace(
            content='{"grounding":0.9,"clarity":0.8,"answerability":0.85,"reason":"ok"}'
        )

    monkeypatch.setattr(MODULE.llm, "invoke", invoke)
    budget = CostBudget(0.01, 0.3, 0.6)
    report = MODULE.llm_sample_report(workspace, 1, budget)

    assert report["grounding"] == 0.9
    assert report["reserved_cost"] > 0
    assert calls[0][1]["max_tokens"] == 250
