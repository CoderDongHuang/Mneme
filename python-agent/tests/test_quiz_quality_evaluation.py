import importlib.util
from pathlib import Path


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
