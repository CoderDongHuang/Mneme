from app.knowledge.lexical_index import LexicalIndex
import sqlite3
import pytest


def test_lexical_index_replaces_and_deletes_documents(tmp_path):
    index = LexicalIndex(str(tmp_path / "lexical.sqlite3"))
    index.replace_document(
        "user-1",
        "kb-1",
        "doc-1",
        [
            {
                "id": "chunk-1",
                "content": "链式法则用于复合函数求导",
                "metadata": {
                    "source": "math.md",
                    "page": 2,
                    "section": "导数",
                    "chunk_type": "text",
                    "parser": "test",
                },
            }
        ],
    )

    results = index.search("user-1", "kb-1", "链式法则", 5)
    assert results[0]["id"] == "chunk-1"
    assert results[0]["metadata"]["page"] == 2

    index.replace_document(
        "user-1",
        "kb-1",
        "doc-1",
        [
            {
                "id": "chunk-2",
                "content": "梯度下降更新模型参数",
                "metadata": {
                    "source": "math.md",
                    "page": 3,
                    "section": "优化",
                    "chunk_type": "text",
                    "parser": "test",
                },
            }
        ],
    )
    assert index.search("user-1", "kb-1", "链式法则", 5) == []
    assert index.search("user-1", "kb-1", "梯度下降", 5)[0]["id"] == "chunk-2"
    assert index.delete_document("user-1", "kb-1", "doc-1") == 1
    assert index.search("user-1", "kb-1", "梯度下降", 5) == []


def test_lexical_index_isolated_by_user_and_knowledge_base(tmp_path):
    index = LexicalIndex(str(tmp_path / "lexical.sqlite3"))
    chunk = {
        "id": "chunk-1",
        "content": "唯一术语 Mneme-42",
        "metadata": {
            "source": "a.md",
            "page": 0,
            "section": "",
            "chunk_type": "text",
            "parser": "test",
        },
    }
    index.replace_document("user-1", "kb-1", "doc-1", [chunk])
    assert index.search("user-1", "kb-1", "Mneme-42", 5)
    assert index.search("user-2", "kb-1", "Mneme-42", 5) == []
    assert index.search("user-1", "kb-2", "Mneme-42", 5) == []


def mutate(index, operation):
    if operation == "replace_document":
        return index.replace_document("u", "kb", "doc", [{"id": "new", "content": "new text"}])
    return getattr(index, operation)(*(
        ("u", "kb", "doc") if operation == "delete_document" else
        ("u", "kb") if operation == "delete_collection" else ("u",)
    ))


@pytest.mark.parametrize("operation", ["replace_document", "delete_document", "delete_collection", "delete_user"])
@pytest.mark.parametrize("failure", ["readonly", "locked", "disk_full", "unavailable"])
def test_mutation_errors_propagate_and_retry_cleans_only_owner(tmp_path, monkeypatch, operation, failure):
    index = LexicalIndex(str(tmp_path / "lexical.sqlite3"))
    for user, kb, doc in (("u", "kb", "doc"), ("other", "kb", "doc")):
        index.replace_document(user, kb, doc, [{"id": user, "content": "original evidence"}])
    connect = index._connect
    blocker = None
    if failure == "readonly":
        monkeypatch.setattr(index, "_connect", lambda: sqlite3.connect(index.path.as_uri() + "?mode=ro", uri=True))
    elif failure == "locked":
        blocker = connect()
        blocker.execute("BEGIN EXCLUSIVE")
        monkeypatch.setattr(index, "_connect", lambda: sqlite3.connect(index.path, timeout=0))
    elif failure == "unavailable":
        index._available = False
        def offline():
            raise sqlite3.OperationalError("unable to open database file")
        monkeypatch.setattr(index, "_connect", offline)
    else:
        def disk_full():
            raise sqlite3.OperationalError("database or disk is full")
        monkeypatch.setattr(index, "_connect", disk_full)
    try:
        with pytest.raises(sqlite3.OperationalError):
            mutate(index, operation)
    finally:
        if blocker:
            blocker.rollback()
            blocker.close()
        monkeypatch.setattr(index, "_connect", connect)
    # Failure did not erase the previous revision or another tenant.
    with connect() as connection:
        assert connection.execute("SELECT count(*) FROM lexical_chunks").fetchone()[0] == 2
    mutate(index, operation)
    with connect() as connection:
        assert connection.execute("SELECT content FROM lexical_chunks WHERE user_id='other'").fetchone()[0] == "original evidence"
        own = connection.execute("SELECT content FROM lexical_chunks WHERE user_id='u'").fetchall()
        assert [row[0] for row in own] == (["new text"] if operation == "replace_document" else [])


def test_partial_replacement_rolls_back_old_revision(tmp_path, monkeypatch):
    index = LexicalIndex(str(tmp_path / "lexical.sqlite3"))
    index.replace_document("u", "kb", "doc", [{"id": "old", "content": "original evidence"}])
    connect = index._connect
    class FailingInsert:
        def __enter__(self):
            self.connection = connect()
            self.connection.__enter__()
            return self
        def __exit__(self, *args):
            try:
                return self.connection.__exit__(*args)
            finally:
                self.connection.close()
        def execute(self, *args):
            return self.connection.execute(*args)
        def executemany(self, *args):
            raise sqlite3.OperationalError("database or disk is full")
    monkeypatch.setattr(index, "_connect", FailingInsert)
    with pytest.raises(sqlite3.OperationalError):
        mutate(index, "replace_document")
    with connect() as connection:
        assert connection.execute("SELECT content FROM lexical_chunks").fetchone()[0] == "original evidence"
