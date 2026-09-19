import argparse
import json
import os
import sys
from pathlib import Path


AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))

from app.utils.llm import llm  # noqa: E402
from scripts.quality_policy import CostBudget, require_sanitized  # noqa: E402


def _questions(workspace: dict) -> list[dict]:
    result = []
    for quiz in workspace.get("quizzes", []):
        value = quiz.get("questions_json", [])
        questions = json.loads(value) if isinstance(value, str) else value
        if not isinstance(questions, list):
            continue
        for question in questions:
            if isinstance(question, dict):
                result.append({"quiz": quiz.get("title", ""), **question})
    return result


def _valid_choice(question: dict) -> bool:
    options = [str(option).strip() for option in question.get("options", [])]
    answer = str(question.get("answer", "")).strip()
    return len(options) >= 2 and len(set(options)) == len(options) and answer in options


def deterministic_report(workspace: dict) -> dict:
    questions = _questions(workspace)
    issues = []
    evidence_backed = 0
    source_backed = 0
    structurally_valid = 0
    for index, question in enumerate(questions, start=1):
        question_issues = []
        prompt = str(question.get("prompt", "")).strip()
        question_type = str(question.get("type", ""))
        answer = str(question.get("answer", "")).strip()
        evidence = str(question.get("evidence", "")).strip()
        source = question.get("source")
        key_points = [str(item).strip() for item in question.get("key_points", [])]
        if not prompt or not answer or question_type not in {"choice", "short"}:
            question_issues.append("missing_required_fields")
        elif question_type == "choice" and not _valid_choice(question):
            question_issues.append("invalid_choice_options")
        elif question_type == "short" and not any(key_points):
            question_issues.append("missing_key_points")
        else:
            structurally_valid += 1
        if evidence:
            evidence_backed += 1
        else:
            question_issues.append("missing_evidence")
        if isinstance(source, dict) and any(source.values()):
            source_backed += 1
        else:
            question_issues.append("missing_source")
        if question_issues:
            issues.append({"index": index, "prompt": prompt, "issues": question_issues})
    denominator = max(1, len(questions))
    return {
        "quizzes": len(workspace.get("quizzes", [])),
        "questions": len(questions),
        "structural_validity": round(structurally_valid / denominator, 4),
        "evidence_coverage": round(evidence_backed / denominator, 4),
        "source_coverage": round(source_backed / denominator, 4),
        "issues": issues,
    }


def llm_sample_report(
    workspace: dict,
    sample_size: int,
    budget: CostBudget | None = None,
) -> dict:
    questions = _questions(workspace)[: max(0, sample_size)]
    if questions and not llm.configured:
        raise RuntimeError("真实测验质量评测需要 DEEPSEEK_API_KEY 或 DASHSCOPE_API_KEY")
    scores = []
    for index, question in enumerate(questions, start=1):
        serialized = json.dumps(question, ensure_ascii=False)
        if budget:
            budget.reserve(
                input_tokens=max(1, len(serialized) // 2),
                output_tokens=250,
                label=f"测验样本 {index}",
            )
        response = llm.invoke(
            [
                (
                    "system",
                    "你是学习测验评审员。仅返回 JSON："
                    '{"grounding":0.0,"clarity":0.0,"answerability":0.0,"reason":""}。'
                    "分数范围 0 到 1，依据题目、答案、证据和来源判断。",
                ),
                ("human", json.dumps(question, ensure_ascii=False)),
            ],
            max_tokens=250,
        )
        text = str(getattr(response, "content", response))
        start, end = text.find("{"), text.rfind("}")
        judged = json.loads(text[start : end + 1])
        scores.append({
            "prompt": question.get("prompt", ""),
            "grounding": float(judged["grounding"]),
            "clarity": float(judged["clarity"]),
            "answerability": float(judged["answerability"]),
            "reason": str(judged.get("reason", "")),
        })
    return {
        "status": "completed" if scores else "disabled",
        "samples": len(scores),
        "grounding": round(sum(item["grounding"] for item in scores) / max(1, len(scores)), 4),
        "clarity": round(sum(item["clarity"] for item in scores) / max(1, len(scores)), 4),
        "answerability": round(
            sum(item["answerability"] for item in scores) / max(1, len(scores)), 4
        ),
        "reserved_cost": round(budget.reserved_usd, 6) if budget else 0.0,
        "max_cost": budget.max_usd if budget else 0.0,
        "details": scores,
    }


def apply_thresholds(report: dict, thresholds: dict) -> list[str]:
    failures = []
    for metric, rule in thresholds.items():
        if metric not in report:
            failures.append(f"missing metric: {metric}")
            continue
        value = float(report[metric])
        if "min" in rule and value < float(rule["min"]):
            failures.append(f"{metric}={value} is below {rule['min']}")
    return failures


def main() -> None:
    parser = argparse.ArgumentParser(description="评估 Mneme 工作区导出的测验质量")
    parser.add_argument("workspace", type=Path)
    parser.add_argument("--llm-sample-size", type=int, default=0)
    parser.add_argument("--thresholds", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--require-sanitized", action="store_true")
    parser.add_argument(
        "--input-cost-per-million",
        type=float,
        default=float(os.getenv("QUIZ_INPUT_COST_PER_MILLION", "0")),
    )
    parser.add_argument(
        "--output-cost-per-million",
        type=float,
        default=float(os.getenv("QUIZ_OUTPUT_COST_PER_MILLION", "0")),
    )
    parser.add_argument("--max-estimated-cost", type=float, default=0.0)
    arguments = parser.parse_args()
    workspace = json.loads(arguments.workspace.read_text(encoding="utf-8"))
    if arguments.require_sanitized:
        require_sanitized(workspace)
    budget = (
        CostBudget(
            arguments.max_estimated_cost,
            arguments.input_cost_per_million,
            arguments.output_cost_per_million,
        )
        if arguments.llm_sample_size > 0
        else None
    )
    report = deterministic_report(workspace)
    report["real_llm_evaluation"] = llm_sample_report(
        workspace, arguments.llm_sample_size, budget
    )
    thresholds = (
        json.loads(arguments.thresholds.read_text(encoding="utf-8"))
        if arguments.thresholds
        else {}
    )
    failures = apply_thresholds(report["real_llm_evaluation"], thresholds)
    report["quality_gate"] = {
        "status": "failed" if failures else "passed",
        "thresholds": thresholds,
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
