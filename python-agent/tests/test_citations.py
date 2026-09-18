from app.knowledge.citations import select_citations


def test_final_citations_stay_with_strongest_document():
    chunks = [
        {"id": "a1", "metadata": {"document_id": "a", "page": 1}},
        {"id": "b1", "metadata": {"document_id": "b", "page": 1}},
        {"id": "a2", "metadata": {"document_id": "a", "page": 2}},
    ]
    assert [item["id"] for item in select_citations(chunks)] == ["a1", "a2"]


def test_final_citations_honor_limit_and_empty_input():
    chunks = [
        {"id": str(index), "metadata": {"document_id": "a"}}
        for index in range(5)
    ]
    assert len(select_citations(chunks, max_citations=2)) == 2
    assert select_citations([]) == []
