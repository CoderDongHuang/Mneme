import argparse
import json
import sys
from pathlib import Path


AGENT_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = AGENT_DIR.parent
sys.path.insert(0, str(AGENT_DIR))

from app.knowledge.ingestion import ingest_document  # noqa: E402
from app.knowledge.retriever import retrieve  # noqa: E402
from app.knowledge.vector_store import vector_store  # noqa: E402


def evaluate(dataset_path: Path, top_k: int, keep: bool) -> dict:
    cases = json.loads(dataset_path.read_text(encoding="utf-8"))
    user_id = "rag_evaluation"
    kb_id = "baseline"
    vector_store.delete_collection(user_id, kb_id)

    sources = sorted({case["expected_source"] for case in cases})
    for source in sources:
        fixture = PROJECT_DIR / "test-fixtures" / source
        if not fixture.is_file():
            raise FileNotFoundError(f"评测资料不存在: {fixture}")
        ingest_document(user_id, kb_id, str(fixture), source_name=source)

    hits = 0
    reciprocal_rank = 0.0
    metadata_complete = 0
    retrieved_total = 0
    details = []
    for case in cases:
        chunks = retrieve(user_id, kb_id, case["question"], top_k)
        rank = None
        for index, chunk in enumerate(chunks, start=1):
            metadata = chunk.get("metadata", {})
            retrieved_total += 1
            if all(key in metadata for key in ("document_id", "source", "page", "section", "chunk_type")):
                metadata_complete += 1
            if (
                rank is None
                and metadata.get("source") == case["expected_source"]
                and all(term in chunk.get("content", "") for term in case["expected_terms"])
            ):
                rank = index
        if rank:
            hits += 1
            reciprocal_rank += 1 / rank
        details.append({"question": case["question"], "rank": rank, "chunks": len(chunks)})

    count = max(1, len(cases))
    report = {
        "cases": len(cases),
        f"hit@{top_k}": round(hits / count, 4),
        "mrr": round(reciprocal_rank / count, 4),
        "citation_metadata_completeness": round(
            metadata_complete / max(1, retrieved_total), 4
        ),
        "details": details,
    }
    if not keep:
        vector_store.delete_collection(user_id, kb_id)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Mneme RAG 基线评测")
    parser.add_argument(
        "--dataset",
        type=Path,
        default=AGENT_DIR / "evaluation" / "rag_cases.json",
    )
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--keep", action="store_true")
    arguments = parser.parse_args()
    print(json.dumps(evaluate(arguments.dataset, arguments.top_k, arguments.keep), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
