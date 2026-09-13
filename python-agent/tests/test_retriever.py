from unittest.mock import patch

from app.knowledge.retriever import retrieve, rewrite_queries


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
    assert chunks == sorted(chunks, key=lambda chunk: chunk["score"], reverse=True)


def test_empty_query_does_not_search():
    with patch("app.knowledge.retriever.vector_store.get_collection", return_value=FakeCollection()):
        assert retrieve("u1", "kb1", "   ") == []
