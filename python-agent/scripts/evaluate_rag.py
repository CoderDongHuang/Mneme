import argparse
import json
import os
import sys
import time
from pathlib import Path


AGENT_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = AGENT_DIR.parent
sys.path.insert(0, str(AGENT_DIR))

from app.knowledge.ingestion import ingest_document  # noqa: E402
from app.knowledge.retriever import retrieve  # noqa: E402
from app.knowledge.vector_store import vector_store  # noqa: E402


def _fixture_path(case: dict) -> Path:
    fixture = Path(str(case.get("fixture") or case.get("expected_source", "")))
    candidates = [
        fixture,
        AGENT_DIR / fixture,
        PROJECT_DIR / fixture,
        PROJECT_DIR / "test-fixtures" / fixture.name,
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"评测资料不存在: {fixture}")


def _expected_sources(case: dict) -> set[str]:
    values = case.get("expected_sources")
    if values is None:
        values = [case.get("expected_source", "")]
    return {str(value) for value in values if str(value).strip()}


def _relevant(chunk: dict, case: dict) -> bool:
    metadata = chunk.get("metadata", {})
    if metadata.get("source") not in _expected_sources(case):
        return False
    content = str(chunk.get("content", "")).casefold()
    if not all(
        str(term).casefold() in content for term in case.get("expected_terms", [])
    ):
        return False
    expected_page = case.get("expected_page")
    return expected_page is None or metadata.get("page") == expected_page


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = min(
        len(ordered) - 1,
        max(0, int((len(ordered) - 1) * percentile)),
    )
    return ordered[position]


def _case_fixture_source(case: dict) -> str:
    return str(
        case.get("source_name")
        or case.get("expected_source")
        or _fixture_path(case).name
    )


def evaluate(
    dataset_path: Path,
    top_k: int,
    keep: bool,
    input_cost_per_million: float = 0.0,
) -> dict:
    cases = json.loads(dataset_path.read_text(encoding="utf-8"))
    if not isinstance(cases, list) or not cases:
        raise ValueError("评测集必须是非空 JSON 数组")
    user_id = "rag_evaluation"
    kb_id = "baseline"
    vector_store.delete_collection(user_id, kb_id)

    fixtures = {}
    for case in cases:
        fixtures[_case_fixture_source(case)] = _fixture_path(case)
    for source, fixture in fixtures.items():
        ingest_document(user_id, kb_id, str(fixture), source_name=source)

    latencies: list[float] = []
    hits = 0
    reciprocal_rank = 0.0
    answerable_count = 0
    answerable_hits = 0
    abstention_hits = 0
    faithfulness_hits = 0
    metadata_complete = 0
    retrieved_total = 0
    relevant_retrieved = 0
    citation_recall_hits = 0
    input_tokens = 0
    details = []
    category_stats: dict[str, dict[str, int]] = {}

    for case in cases:
        started = time.perf_counter()
        chunks = retrieve(user_id, kb_id, case["question"], top_k)
        latency_ms = (time.perf_counter() - started) * 1000
        latencies.append(latency_ms)
        answerable = bool(case.get("answerable", True))
        category = str(case.get("category", "general"))
        stats = category_stats.setdefault(category, {"cases": 0, "hits": 0})
        stats["cases"] += 1

        relevant_ranks = [
            index
            for index, chunk in enumerate(chunks, start=1)
            if _relevant(chunk, case)
        ]
        rank = relevant_ranks[0] if relevant_ranks else None
        relevant_count = len(relevant_ranks)
        retrieved_total += len(chunks)
        relevant_retrieved += relevant_count
        citation_recall_hits += bool(rank)
        input_tokens += sum(
            max(1, len(str(chunk.get("content", ""))) // 4) for chunk in chunks
        )
        metadata_complete += sum(
            all(
                key in chunk.get("metadata", {})
                for key in ("document_id", "source", "page", "section", "chunk_type")
            )
            for chunk in chunks
        )

        if answerable:
            answerable_count += 1
            if rank:
                answerable_hits += 1
                hits += 1
                reciprocal_rank += 1 / rank
                stats["hits"] += 1
            evidence_terms = case.get("expected_terms", [])
            top_content = (
                str(chunks[0].get("content", "")).casefold() if chunks else ""
            )
            faithfulness_hits += bool(
                rank
                and all(
                    str(term).casefold() in top_content for term in evidence_terms
                )
            )
        else:
            abstention_hits += int(not relevant_ranks)

        details.append(
            {
                "question": case["question"],
                "category": category,
                "answerable": answerable,
                "rank": rank,
                "chunks": len(chunks),
                "latency_ms": round(latency_ms, 2),
            }
        )

    count = max(1, len(cases))
    answerable_denominator = max(1, answerable_count)
    unanswerable_count = count - answerable_count
    estimated_cost = input_tokens / 1_000_000 * max(0.0, input_cost_per_million)
    report = {
        "cases": len(cases),
        "answerable_cases": answerable_count,
        "unanswerable_cases": unanswerable_count,
        f"hit@{top_k}": round(hits / answerable_denominator, 4),
        f"recall@{top_k}": round(answerable_hits / answerable_denominator, 4),
        "mrr": round(reciprocal_rank / answerable_denominator, 4),
        "faithfulness_proxy": round(faithfulness_hits / answerable_denominator, 4),
        "citation_metadata_completeness": round(
            metadata_complete / max(1, retrieved_total), 4
        ),
        "citation_precision": round(
            relevant_retrieved / max(1, retrieved_total), 4
        ),
        "citation_recall": round(
            citation_recall_hits / answerable_denominator, 4
        ),
        "abstention_proxy": round(
            abstention_hits / max(1, unanswerable_count), 4
        ),
        "mean_latency_ms": round(sum(latencies) / count, 2),
        "p95_latency_ms": round(_percentile(latencies, 0.95), 2),
        "estimated_input_tokens": input_tokens,
        "estimated_input_cost": round(estimated_cost, 6),
        "cost_assumption_usd_per_million_input_tokens": input_cost_per_million,
        "category_stats": category_stats,
        "details": details,
    }
    if not keep:
        vector_store.delete_collection(user_id, kb_id)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Mneme RAG 离线评测")
    parser.add_argument(
        "--dataset",
        type=Path,
        default=AGENT_DIR / "evaluation" / "rag_cases.json",
    )
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument(
        "--input-cost-per-million",
        type=float,
        default=float(os.getenv("RAG_INPUT_COST_PER_MILLION", "0")),
    )
    parser.add_argument("--keep", action="store_true")
    arguments = parser.parse_args()
    print(
        json.dumps(
            evaluate(
                arguments.dataset,
                arguments.top_k,
                arguments.keep,
                arguments.input_cost_per_million,
            ),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
