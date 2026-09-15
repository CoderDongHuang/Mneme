from app.knowledge.lexical_index import LexicalIndex


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
