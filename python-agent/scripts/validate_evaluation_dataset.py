"""Validate versioned, sanitized target-domain evaluation assets."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))

from scripts.quality_policy import require_sanitized  # noqa: E402


def load_manifest(path: Path) -> dict:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("评测 manifest 必须是 JSON 对象")
    required = {"dataset_id", "version", "domain", "data_classification", "sanitized"}
    missing = sorted(required - set(manifest))
    if missing:
        raise ValueError(f"评测 manifest 缺少字段: {', '.join(missing)}")
    if manifest["sanitized"] is not True:
        raise ValueError("目标领域评测集必须显式标记 sanitized=true")
    return manifest


def validate(manifest_path: Path) -> dict:
    root = manifest_path.parent
    manifest = load_manifest(manifest_path)
    rag = json.loads((root / manifest["rag_dataset"]).read_text(encoding="utf-8"))
    quiz = json.loads((root / manifest["quiz_dataset"]).read_text(encoding="utf-8"))
    document_ai = json.loads((root / manifest["document_ai_dataset"]).read_text(encoding="utf-8"))
    require_sanitized(rag)
    require_sanitized(quiz)
    require_sanitized(document_ai)
    quiz_count = sum(
        len(json.loads(item.get("questions_json", "[]")) if isinstance(item.get("questions_json"), str) else item.get("questions_json", []))
        for item in quiz.get("quizzes", [])
    )
    counts = {
        "rag": len(rag),
        "quiz": quiz_count,
        "document_ai": len(document_ai),
        "embedding": len(manifest.get("embedding_cases", [])),
    }
    failures = [
        f"{name}={count} below {manifest['minimum_samples'][name]}"
        for name, count in counts.items()
        if count < int(manifest["minimum_samples"].get(name, 0))
    ]
    if failures:
        raise ValueError("目标领域评测集样本数不足: " + ", ".join(failures))
    return {
        "dataset_id": manifest["dataset_id"],
        "version": manifest["version"],
        "domain": manifest["domain"],
        "data_classification": manifest["data_classification"],
        "counts": counts,
        "status": "passed",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    print(json.dumps(validate(args.manifest), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
