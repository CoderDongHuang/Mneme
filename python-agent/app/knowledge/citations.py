"""Evidence numbering shared by the prompt, synchronous API and SSE API."""
from __future__ import annotations

import re

NO_EVIDENCE_ANSWER = "当前资料没有足够的可核查证据回答这个问题。请补充相关文档，或说明需要查询的具体范围。"
INVALID_EVIDENCE_ANSWER = "本次回答未能提供有效的资料引用，已停止展示未经核验的结论。请补充资料或缩小问题范围后重试。"


def select_citations(chunks: list[dict], max_citations: int = 20) -> list[dict]:
    """Keep context order: [n] must always identify the nth displayed passage.

    Multiple documents are allowed. Deduplication belongs to retrieval, before
    numbering; dropping passages here would silently change citation numbers.
    """
    return chunks[:max(0, max_citations)]


def validate_evidence_answer(state: dict, answer: str) -> str:
    """Fail closed on absent evidence or fabricated reference numbers.

    This checks reference structure, not semantic entailment. The latter still
    requires model evaluation and human review.
    """
    if state.get("intent") != "qa":
        return answer
    chunks = state.get("retrieved_chunks", [])
    if not chunks:
        return NO_EVIDENCE_ANSWER
    references = [int(value) for value in re.findall(r"\[(\d+)\]", answer)]
    if not references or any(index < 1 or index > len(chunks) for index in references):
        return INVALID_EVIDENCE_ANSWER
    return answer
