from app.knowledge.citations import (
    select_citations, validate_evidence_answer, NO_EVIDENCE_ANSWER, INVALID_EVIDENCE_ANSWER,
)


def test_cross_document_numbering_matches_prompt_order():
    chunks = [{"id": "a1"}, {"id": "b1"}, {"id": "a2"}]
    assert select_citations(chunks) == chunks
    assert select_citations(chunks, 2) == chunks[:2]
    assert select_citations(chunks, 0) == []


def test_refuse_no_evidence_and_fabricated_reference():
    assert validate_evidence_answer({"intent": "qa"}, "invented fact [1]") == NO_EVIDENCE_ANSWER
    state = {"intent": "qa", "retrieved_chunks": [{"id": "a"}, {"id": "b"}]}
    for answer in ("no citation", "invented [3]", "invalid [0]", "mixed [1] [999]"):
        assert validate_evidence_answer(state, answer) == INVALID_EVIDENCE_ANSWER
    assert validate_evidence_answer(state, "one [1], two [2]") == "one [1], two [2]"
    assert validate_evidence_answer({"intent": "general"}, "hello") == "hello"
