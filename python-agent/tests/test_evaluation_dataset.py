import json
from pathlib import Path


def test_offline_rag_dataset_has_structured_coverage():
    dataset = json.loads(
        (Path(__file__).parents[1] / "evaluation" / "rag_cases.json").read_text(
            encoding="utf-8"
        )
    )
    assert len(dataset) >= 100
    assert {"roadmap", "metrics", "parser", "memory", "unanswerable"} <= {
        case["category"] for case in dataset
    }
    assert sum(not case.get("answerable", True) for case in dataset) >= 5
