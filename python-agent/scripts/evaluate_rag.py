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
from app.knowledge.citations import select_citations  # noqa: E402
from app.knowledge.retriever import retrieve  # noqa: E402
from app.knowledge.vector_store import vector_store  # noqa: E402
from app.utils.llm import llm  # noqa: E402
from scripts.quality_policy import CostBudget, require_sanitized  # noqa: E402


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


def _content(response: object) -> str:
    value = getattr(response, "content", response)
    if isinstance(value, list):
        return "".join(
            str(item.get("text", "") if isinstance(item, dict) else item)
            for item in value
        )
    return str(value)


def _json_object(text: str) -> dict:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("评测模型未返回 JSON 对象")
    value = json.loads(text[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("评测模型返回结构无效")
    return value


def _real_llm_scores(question: str, chunks: list[dict]) -> dict:
    evidence = "\n\n".join(
        f"[{index}] {chunk.get('content', '')}"
        for index, chunk in enumerate(chunks[:5], start=1)
    )
    answer = _content(
        llm.invoke(
            [
                ("system", "只能依据给定证据回答；证据不足时明确说不知道，并引用证据编号。"),
                ("human", f"问题：{question}\n\n证据：\n{evidence}"),
            ],
            max_tokens=400,
        )
    )
    judge_response = _content(
        llm.invoke(
            [
                (
                    "system",
                    "你是严格的 RAG 评测器。仅返回 JSON，分数范围 0 到 1："
                    '{"faithfulness":0.0,"answer_relevance":0.0,"reason":""}。'
                    "faithfulness 衡量回答是否完全由证据支持；answer_relevance 衡量是否直接回答问题。",
                ),
                (
                    "human",
                    f"问题：{question}\n\n证据：\n{evidence}\n\n待评回答：\n{answer}",
                ),
            ],
            max_tokens=200,
        )
    )
    judged = _json_object(judge_response)
    return {
        "answer": answer,
        "faithfulness": max(0.0, min(1.0, float(judged["faithfulness"]))),
        "answer_relevance": max(
            0.0, min(1.0, float(judged["answer_relevance"]))
        ),
        "reason": str(judged.get("reason", "")),
        "estimated_input_tokens": max(
            1, (len(question) * 2 + len(evidence) * 2 + len(answer)) // 4
        ),
        "estimated_output_tokens": max(
            1, (len(answer) + len(judge_response)) // 4
        ),
    }


def evaluate(
    dataset_path: Path,
    top_k: int,
    keep: bool,
    input_cost_per_million: float = 0.0,
    llm_sample_size: int = 0,
    output_cost_per_million: float = 0.0,
    max_estimated_cost: float = 0.0,
    require_sanitized_dataset: bool = False,
) -> dict:
    cases = json.loads(dataset_path.read_text(encoding="utf-8"))
    if not isinstance(cases, list) or not cases:
        raise ValueError("评测集必须是非空 JSON 数组")
    if require_sanitized_dataset:
        require_sanitized(cases)
    budget = (
        CostBudget(
            max_estimated_cost,
            input_cost_per_million,
            output_cost_per_million,
        )
        if llm_sample_size > 0
        else None
    )
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
    llm_details: list[dict] = []

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
        final_citations = select_citations(chunks)
        relevant_citations = [
            chunk for chunk in final_citations if _relevant(chunk, case)
        ]
        retrieved_total += len(chunks)
        relevant_retrieved += len(relevant_citations)
        citation_recall_hits += bool(relevant_citations)
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
                "citations": len(final_citations),
                "relevant_citations": len(relevant_citations),
                "latency_ms": round(latency_ms, 2),
            }
        )
        if answerable and chunks and len(llm_details) < max(0, llm_sample_size):
            if not llm.configured:
                raise RuntimeError("真实模型评测需要 DEEPSEEK_API_KEY 或 DASHSCOPE_API_KEY")
            evidence_chars = sum(len(str(chunk.get("content", ""))) for chunk in chunks[:5])
            budget.reserve(
                input_tokens=max(1, (evidence_chars * 2 + len(case["question"]) * 4) // 4) + 400,
                output_tokens=600,
                label=f"RAG 样本 {len(llm_details) + 1}",
            )
            scores = _real_llm_scores(case["question"], chunks)
            llm_details.append({"question": case["question"], **scores})

    count = max(1, len(cases))
    answerable_denominator = max(1, answerable_count)
    unanswerable_count = count - answerable_count
    estimated_cost = input_tokens / 1_000_000 * max(0.0, input_cost_per_million)
    llm_input_tokens = sum(item["estimated_input_tokens"] for item in llm_details)
    llm_output_tokens = sum(item["estimated_output_tokens"] for item in llm_details)
    llm_estimated_cost = (
        llm_input_tokens / 1_000_000 * max(0.0, input_cost_per_million)
        + llm_output_tokens / 1_000_000 * max(0.0, output_cost_per_million)
    )
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
            relevant_retrieved
            / max(1, sum(item["citations"] for item in details)),
            4,
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
        "real_llm_evaluation": {
            "status": "completed" if llm_details else "disabled",
            "samples": len(llm_details),
            "faithfulness": round(
                sum(item["faithfulness"] for item in llm_details)
                / max(1, len(llm_details)),
                4,
            ),
            "answer_relevance": round(
                sum(item["answer_relevance"] for item in llm_details)
                / max(1, len(llm_details)),
                4,
            ),
            "estimated_input_tokens": llm_input_tokens,
            "estimated_output_tokens": llm_output_tokens,
            "estimated_cost": round(llm_estimated_cost, 6),
            "reserved_cost": round(budget.reserved_usd, 6) if budget else 0.0,
            "max_cost": max_estimated_cost,
            "cost_assumption_usd_per_million_output_tokens": output_cost_per_million,
            "details": llm_details,
        },
    }
    if not keep:
        vector_store.delete_collection(user_id, kb_id)
    return report


def apply_thresholds(report: dict, thresholds: dict) -> list[str]:
    failures = []
    for metric, rule in thresholds.items():
        if metric not in report:
            failures.append(f"missing metric: {metric}")
            continue
        value = float(report[metric])
        if "min" in rule and value < float(rule["min"]):
            failures.append(f"{metric}={value} is below {rule['min']}")
        if "max" in rule and value > float(rule["max"]):
            failures.append(f"{metric}={value} exceeds {rule['max']}")
    return failures


def apply_real_llm_thresholds(report: dict, thresholds: dict) -> list[str]:
    evaluation = report.get("real_llm_evaluation", {})
    if evaluation.get("status") != "completed":
        return ["real_llm_evaluation was not completed"]
    return [f"real_llm_evaluation.{failure}" for failure in apply_thresholds(evaluation, thresholds)]


def main() -> None:
    parser = argparse.ArgumentParser(description="Mneme RAG 离线评测")
    parser.add_argument(
        "--dataset",
        type=Path,
        default=AGENT_DIR / "evaluation" / "rag_cases.json",
    )
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument(
        "--thresholds",
        type=Path,
        default=AGENT_DIR / "evaluation" / "rag_thresholds.json",
    )
    parser.add_argument("--report", type=Path)
    parser.add_argument(
        "--input-cost-per-million",
        type=float,
        default=float(os.getenv("RAG_INPUT_COST_PER_MILLION", "0")),
    )
    parser.add_argument("--keep", action="store_true")
    parser.add_argument(
        "--llm-sample-size",
        type=int,
        default=0,
        help="使用真实回答与评判模型计算 Faithfulness/Answer Relevance 的样本数",
    )
    parser.add_argument(
        "--output-cost-per-million",
        type=float,
        default=float(os.getenv("RAG_OUTPUT_COST_PER_MILLION", "0")),
    )
    parser.add_argument("--max-estimated-cost", type=float, default=0.0)
    parser.add_argument("--require-sanitized", action="store_true")
    parser.add_argument("--real-llm-thresholds", type=Path)
    arguments = parser.parse_args()
    report = evaluate(
                arguments.dataset,
                arguments.top_k,
                arguments.keep,
                arguments.input_cost_per_million,
                arguments.llm_sample_size,
                arguments.output_cost_per_million,
                arguments.max_estimated_cost,
                arguments.require_sanitized,
            )
    thresholds = json.loads(arguments.thresholds.read_text(encoding="utf-8"))
    failures = apply_thresholds(report, thresholds)
    if arguments.real_llm_thresholds:
        real_thresholds = json.loads(
            arguments.real_llm_thresholds.read_text(encoding="utf-8")
        )
        failures.extend(apply_real_llm_thresholds(report, real_thresholds))
    else:
        real_thresholds = None
    report["quality_gate"] = {
        "status": "failed" if failures else "passed",
        "thresholds": thresholds,
        "real_llm_thresholds": real_thresholds,
        "failures": failures,
    }
    output = json.dumps(report, ensure_ascii=False, indent=2)
    if arguments.report:
        arguments.report.parent.mkdir(parents=True, exist_ok=True)
        arguments.report.write_text(output + "\n", encoding="utf-8")
    print(output)
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
