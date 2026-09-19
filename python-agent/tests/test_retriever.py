from unittest.mock import patch

from app.knowledge.retriever import (
    _ann_semantic_candidates,
    _exact_semantic_candidates,
    retrieve,
    rewrite_queries,
)


class FakeCollection:
    documents = [
        "反向传播通过链式法则计算神经网络梯度",
        "番茄工作法使用专注周期管理时间",
        "链式法则用于复合函数求导",
    ]

    def count(self):
        return len(self.documents)

    def get(self, **_kwargs):
        return {
            "ids": ["gradient", "pomodoro", "chain"],
            "documents": self.documents,
            "metadatas": [
                {"document_id": "1", "page": 1},
                {"document_id": "1", "page": 2},
                {"document_id": "1", "page": 3},
            ],
        }

    def query(self, query_texts, n_results, include):
        del query_texts, n_results, include
        return {
            "ids": [["pomodoro", "gradient", "chain"]],
            "documents": [[self.documents[1], self.documents[0], self.documents[2]]],
            "metadatas": [[{"page": 2}, {"page": 1}, {"page": 3}]],
            "distances": [[0.1, 0.2, 0.3]],
        }


def test_query_rewrite_removes_polite_document_prefix():
    variants = rewrite_queries("请根据资料解释一下反向传播")
    assert variants[0] == "请根据资料解释一下反向传播"
    assert any("反向传播" in variant for variant in variants[1:])


def test_hybrid_rrf_promotes_lexically_relevant_result():
    with patch("app.knowledge.retriever.vector_store.get_collection", return_value=FakeCollection()):
        chunks = retrieve("u1", "kb1", "反向传播 链式法则", 3)
    assert chunks[0]["id"] in {"gradient", "chain"}
    assert all("score" in chunk for chunk in chunks)
    assert all("term_coverage" in chunk for chunk in chunks)
    assert chunks == sorted(chunks, key=lambda chunk: chunk["score"], reverse=True)


def test_empty_query_does_not_search():
    with patch("app.knowledge.retriever.vector_store.get_collection", return_value=FakeCollection()):
        assert retrieve("u1", "kb1", "   ") == []


def test_semantic_distance_ties_use_stable_chunk_id():
    class TiedCollection:
        def count(self):
            return 2

        def query(self, **_kwargs):
            return {
                "ids": [["chunk-b", "chunk-a"]],
                "documents": [["B", "A"]],
                "metadatas": [[{}, {}]],
                "distances": [[0.5, 0.5]],
            }

    chunks = _ann_semantic_candidates(TiedCollection(), ["query"], 2)

    assert [chunk["id"] for chunk in chunks] == ["chunk-a", "chunk-b"]


def test_exact_semantic_candidates_rank_stored_vectors(monkeypatch):
    class ExactCollection:
        def get(self, **_kwargs):
            return {
                "ids": ["chunk-b", "chunk-a"],
                "documents": ["B", "A"],
                "metadatas": [{}, {}],
                "embeddings": [[1.0, 0.0], [0.0, 1.0]],
            }

    monkeypatch.setattr(
        "app.knowledge.retriever.embeddings",
        lambda _queries: [[0.0, 1.0]],
    )

    chunks = _exact_semantic_candidates(ExactCollection(), ["query"], 2)

    assert [chunk["id"] for chunk in chunks] == ["chunk-a", "chunk-b"]
    assert [chunk["distance"] for chunk in chunks] == [0.0, 2.0]
