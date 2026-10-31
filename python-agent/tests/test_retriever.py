from unittest.mock import patch
from dataclasses import replace
from app.knowledge import retriever

from app.knowledge.retriever import (
    _ann_semantic_candidates,
    _exact_semantic_candidates,
    retrieve,
    rewrite_queries,
    _supported_candidates,
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

    def query(self, query_embeddings, n_results, include, **kwargs):
        del query_embeddings, n_results, include, kwargs
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


def test_query_rewrites_share_one_embedding_request_and_keep_channel_ranks(monkeypatch):
    from unittest.mock import Mock

    embed = Mock(return_value=[[1.0, 0.0], [0.0, 1.0]])
    monkeypatch.setattr(retriever, "embeddings", embed)
    collection = Mock()
    collection.count.return_value = 2
    collection.query.return_value = {
        "ids": [["a", "b"], ["b", "a"]],
        "documents": [["A", "B"], ["B", "A"]],
        "metadatas": [[{}, {}], [{}, {}]],
        "distances": [[0.1, 0.9], [0.2, 0.8]],
    }
    chunks = _ann_semantic_candidates(collection, ["original", "rewritten"], 5)
    embed.assert_called_once_with(["original", "rewritten"])
    collection.query.assert_called_once_with(
        query_embeddings=embed.return_value, n_results=2,
        include=["documents", "metadatas", "distances"],
    )
    assert [(item["id"], item["query_index"]) for item in chunks] == [
        ("a", 0), ("b", 0), ("b", 1), ("a", 1),
    ]


def test_stale_lexical_hits_are_never_returned(monkeypatch):
    class LiveCollection:
        def count(self):
            return 2

        def get(self, **kwargs):
            if "ids" in kwargs:
                return {"ids": ["live"], "documents": ["current version"],
                        "metadatas": [{"document_id": "new", "visual_region": "0,0,1,1"}]}
            return {"ids": ["live"], "documents": ["current version"], "metadatas": [{"document_id": "new"}]}

    monkeypatch.setattr("app.knowledge.retriever.vector_store.get_collection", lambda *_: LiveCollection())
    monkeypatch.setattr("app.knowledge.retriever._semantic_candidates", lambda *_: [])
    monkeypatch.setattr("app.knowledge.retriever._indexed_candidates", lambda *_: [
        {"id": "deleted", "content": "deleted secret", "metadata": {}, "lexical_score": 10},
        {"id": "live", "content": "old version", "metadata": {}, "lexical_score": 5},
    ])
    results = retrieve("owner", "kb", "version", 5)
    assert [item["id"] for item in results] == ["live"]
    assert results[0]["content"] == "current version"
    assert results[0]["metadata"]["visual_region"] == "0,0,1,1"
    assert results[0]["retrieval_ranks"] == {"bm25": 1}


def test_topic_overlap_cannot_support_a_missing_requested_field():
    candidate = {"id": "a", "content": "飞羽计划的负责人为李安，校验编号为 FY-928。",
                 "metadata": {"source": "银行账户余额.md"}}
    assert _supported_candidates("飞羽计划的银行账户余额是多少？", [candidate]) == []
    assert _supported_candidates("飞羽计划的负责人是谁？", [candidate])


def test_focus_gate_preserves_open_semantic_queries_and_can_be_disabled(monkeypatch):
    candidate = {"id": "a", "content": "参数更新沿着损失下降方向进行"}
    assert _supported_candidates("解释梯度下降", [candidate]) == [candidate]
    monkeypatch.setattr(retriever, "settings", replace(retriever.settings, retriever_focus_gate_enabled=False))
    assert _supported_candidates("飞羽计划的银行卡密码是什么", [candidate]) == [candidate]


def test_focus_gate_accepts_common_field_paraphrases():
    candidates = [
        {"content": "这个产品定价为 320 元。"},
        {"content": "这份讲义由陈安撰写。"},
        {"content": "会议在中心大楼举行。"},
        {"content": "电池可连续工作 10 小时。"},
    ]
    for question, candidate in zip([
        "这个产品的售价是多少？", "讲义的作者是谁？",
        "会议的举办地点在哪里？", "电池的续航时间是多少？",
    ], candidates):
        assert _supported_candidates(question, [candidate])
