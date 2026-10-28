import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from app.knowledge.qdrant_store import VectorClient

spec = importlib.util.spec_from_file_location("vector_migration", Path(__file__).resolve().parents[1] / "scripts" / "migrate_vector_store.py")
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)


def write_snapshot(path, collections):
    encoded = json.dumps({"schema_version": 1, "source": "chroma", "collections": collections}).encode()
    path.write_bytes(encoded)
    path.with_suffix(".json.sha256").write_text(hashlib.sha256(encoded).hexdigest())


def rows(name="docs"):
    return {"collection": name, "metadata": {"user_id": "alice", "kb_id": "kb", "embedding_profile": "old:2"},
            "ids": ["文档_1", "old/id"], "documents": ["original text", None], "metadatas": [{"document_id": "doc", "version": 3}, None], "embeddings": [[0., 1.], [1., 0.]]}


def test_import_preserves_private_payload_vectors_and_source(tmp_path):
    path = tmp_path / "export.json"
    write_snapshot(path, [rows()])
    original = path.read_bytes()
    data, digest = migration.read_snapshot(path)
    client = VectorClient(path=str(tmp_path / "new"), dimension=2)
    assert migration.import_snapshot(client, data, digest)["verified_collections"] == 1
    collection = client.get_collection("docs")
    assert collection.metadata == rows()["metadata"]
    assert collection.get(ids=["文档_1"])["documents"] == ["original text"]
    assert collection.get(ids=["old/id"])["metadatas"] == [None]
    assert collection.query(query_embeddings=[[0., 1.]])["ids"][0][0] == "文档_1"
    assert client.raw.collection_exists(migration.RECEIPT)
    assert [item.name for item in client.list_collections()] == ["docs"]
    assert path.read_bytes() == original
    with pytest.raises(ValueError, match="empty"):
        migration.import_snapshot(client, data, digest)
    path.write_bytes(original + b" ")
    with pytest.raises(ValueError, match="checksum"):
        migration.read_snapshot(path)


def test_migration_rolls_back_target_on_invalid_later_collection(tmp_path):
    path = tmp_path / "export.json"
    bad = rows("bad")
    bad["embeddings"] = [[1., 0., 0.], [0., 1., 0.]]
    write_snapshot(path, [rows(), bad])
    data, digest = migration.read_snapshot(path)
    client = VectorClient(path=str(tmp_path / "new"), dimension=2)
    with pytest.raises(ValueError, match="dimension"):
        migration.import_snapshot(client, data, digest)
    assert not client.raw.get_collections().collections


def test_startup_refuses_empty_target_with_legacy_data(tmp_path, monkeypatch):
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    (legacy / "chroma.sqlite3").write_bytes(b"existing legacy DB")
    monkeypatch.setenv("CHROMA_PATH", str(legacy))
    with pytest.raises(RuntimeError, match="migrate_vector_store"):
        VectorClient(path=str(tmp_path / "new"), check_legacy=True)


def test_receipt_only_target_is_not_fresh(tmp_path):
    client = VectorClient(path=str(tmp_path / "new"), dimension=2)
    client.get_or_create_collection(migration.RECEIPT)
    assert not client.list_collections()
    with pytest.raises(ValueError, match="empty"):
        migration.import_snapshot(client, {"collections": []}, "checksum")
