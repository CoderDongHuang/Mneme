import json
import pytest
from scripts import evaluate_rag


@pytest.mark.parametrize("chunks,expected", [([], 1.0), ([{"content": "unrelated", "metadata": {}}], 0.0)])
def test_unanswerable_metric_requires_actual_empty_retrieval(monkeypatch, tmp_path, chunks, expected):
    fixture = tmp_path / "synthetic.txt"
    fixture.write_text("Synthetic evidence", encoding="utf-8")
    dataset = tmp_path / "cases.json"
    dataset.write_text(json.dumps([{"question": "Missing field?", "fixture": str(fixture),
                                   "expected_sources": [], "answerable": False}]), encoding="utf-8")
    monkeypatch.setattr(evaluate_rag, "ingest_document", lambda *args, **kwargs: None)
    monkeypatch.setattr(evaluate_rag.vector_store, "delete_collection", lambda *args: None)
    monkeypatch.setattr(evaluate_rag, "retrieve", lambda *args: chunks)
    report = evaluate_rag.evaluate(dataset, 5, False)
    assert report["no_answer_evidence_absence"] == expected
    assert report["details"][0]["passed"] == bool(expected)
