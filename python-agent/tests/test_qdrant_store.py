import pytest

from app.knowledge.qdrant_store import VectorClient, InvalidCollectionException


@pytest.fixture
def client(tmp_path):
    return VectorClient(path=str(tmp_path / "vectors"), dimension=2)


def test_persistence_original_ids_pagination_and_partial_update(client, tmp_path):
    collection = client.get_or_create_collection("docs", metadata={"user_id": "alice"})
    collection.add(ids=["a/b", "中文", "c"], documents=["one", "two", "three"],
                   embeddings=[[0., 0.], [3., 4.], [8., 0.]],
                   metadatas=[{"user_id": "a", "tag": "x"}, {"user_id": "b"}, {"user_id": "a"}])
    collection.update(ids=["a/b"], metadatas=[{"frozen": True}])
    row = collection.get(ids=["a/b"], include=["documents", "metadatas", "embeddings"])
    assert row == {"ids": ["a/b"], "documents": ["one"], "metadatas": [{"user_id": "a", "tag": "x", "frozen": True}], "embeddings": [[0., 0.]]}
    again = VectorClient(path=str(tmp_path / "vectors"), dimension=2)
    assert again.raw is client.raw
    assert again.get_collection("docs").metadata == {"user_id": "alice"}
    pages = [collection.get(limit=1, offset=i)["ids"][0] for i in range(3)]
    assert set(pages) == {"a/b", "中文", "c"}
    assert collection.get(limit=0)["ids"] == []
    assert collection.get(limit=2, offset=10)["ids"] == []
    assert collection.get(ids=[])["ids"] == []


def test_filters_distances_batch_queries_and_scoped_deletion(client):
    collection = client.get_or_create_collection("docs")
    collection.add(ids=["a", "b", "c"], embeddings=[[0., 0.], [3., 4.], [6., 8.]],
                   metadatas=[{"user_id": "alice", "tag": "x", "year": 2024}, {"user_id": "alice", "tag": "y", "year": 2025}, {"user_id": "bob", "tag": "x", "year": 2026}])
    where = {"$and": [{"user_id": "alice"}, {"$or": [{"tag": {"$in": ["y"]}}, {"year": {"$lt": 2024}}]}]}
    assert collection.get(where=where)["ids"] == ["b"]
    assert collection.get(where={"tag": {"$in": []}})["ids"] == []
    assert set(collection.get(where={"tag": {"$nin": []}})["ids"]) == {"a", "b", "c"}
    results = collection.query(query_embeddings=[[0., 0.], [6., 8.]], n_results=3)
    assert results["ids"] == [["a", "b", "c"], ["c", "b", "a"]]
    assert results["distances"] == [[0., 25., 100.], [0., 25., 100.]]
    assert collection.query(query_embeddings=[[0., 0.]], n_results=0)["ids"] == [[]]
    assert collection.query(query_embeddings=[[0., 0.]], n_results=1, include=["embeddings"]) == {"ids": [["a"]], "embeddings": [[[0., 0.]]]}
    collection.update(ids=["b"], metadatas=[{"score": 1.5}])
    assert collection.get(where={"score": 1.5})["ids"] == ["b"]
    assert "b" not in collection.get(where={"score": {"$ne": 1.5}})["ids"]
    with pytest.raises(ValueError, match="finite"):
        collection.get(where={"score": float("nan")})
    collection.delete(ids=["a", "c"], where={"user_id": "alice"})
    assert set(collection.get()["ids"]) == {"b", "c"}
    with pytest.raises(ValueError):
        collection.delete()
    with pytest.raises(ValueError):
        collection.get(where={"user_id": {"$unknown": "alice"}})
    client.delete_collection("docs")
    with pytest.raises(InvalidCollectionException):
        client.get_collection("docs")


def test_cosine_distance_and_embedding_contract(client):
    def embed(texts):
        return [[1., 0.] for _ in texts]
    collection = client.get_or_create_collection("cosine", metadata={"hnsw:space": "cosine"}, embedding_function=embed)
    collection.add(ids=["a"], documents=["text"], metadatas=[{"owner": "a"}])
    assert collection.query(query_texts=["text"])["distances"][0][0] == pytest.approx(0)
    with pytest.raises(ValueError, match="distance mismatch"):
        client.get_or_create_collection("cosine", metadata={"hnsw:space": "l2"})
    collection.update(ids=["a"], documents=["new"])
    assert collection.get()["documents"] == ["new"]
    with pytest.raises(ValueError, match="field count"):
        collection.upsert(ids=["x", "y"], embeddings=[[1., 0.]])
