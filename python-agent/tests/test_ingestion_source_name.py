import asyncio
from contextlib import nullcontext
from unittest.mock import Mock

import pytest

from app.api import knowledge
from app.models.knowledge import DocumentIngestRequest
from app.knowledge.generations import StaleGeneration
from fastapi import HTTPException
from pydantic import ValidationError


@pytest.mark.parametrize("source_name", ["学习资料.pdf", None])
def test_durable_ingestion_keeps_display_name_separate_from_storage_path(tmp_path, monkeypatch, source_name):
    stored = tmp_path / "storage-uuid-document.pdf"
    stored.write_bytes(b"fixture")
    ingest = Mock(return_value="doc_7")
    monkeypatch.setattr(knowledge, "ingest_document", ingest)
    monkeypatch.setattr(knowledge, "ingestion_task", lambda *_: nullcontext())
    monkeypatch.setattr(knowledge.vector_store, "get_collection", lambda *_: None)
    request = DocumentIngestRequest(user_id="1", kb_id="2", file_path=str(stored),
                                    document_id="doc_7", source_name=source_name)
    result = asyncio.run(knowledge.ingest_durable(request))
    assert result.document_id == "doc_7"
    assert ingest.call_args.args[2:5] == (str(stored.resolve()), source_name or stored.name, "doc_7")


@pytest.mark.parametrize("document,generation", [(None, 1), ("doc_7", None)])
def test_durable_task_requires_explicit_document_and_generation(monkeypatch, document, generation):
    ingest = Mock()
    monkeypatch.setattr(knowledge, "ingest_document", ingest)
    request = DocumentIngestRequest(user_id="1", kb_id="2", file_path="missing", task_id="task",
                                   document_id=document, index_generation=generation)
    with pytest.raises(HTTPException) as rejected:
        asyncio.run(knowledge.ingest_durable(request))
    assert rejected.value.status_code == 422
    ingest.assert_not_called()


@pytest.mark.parametrize("generation", [0, -1, True, "1", 1.5, 9223372036854775808])
def test_generation_contract_rejects_coercion_and_overflow(generation):
    with pytest.raises(ValidationError):
        DocumentIngestRequest(user_id="1", kb_id="2", file_path="file", index_generation=generation)


def test_background_ingestion_preserves_generation_and_counts_only_active_chunks(tmp_path, monkeypatch):
    source = tmp_path / "source.txt"
    source.write_text("fixture")
    ingest = Mock(return_value="doc_7")
    updated = Mock()
    monkeypatch.setattr(knowledge, "ingest_document", ingest)
    monkeypatch.setattr(knowledge, "update_task", updated)
    monkeypatch.setattr(knowledge.vector_store, "get_collection", lambda *_: object())
    monkeypatch.setattr(knowledge.vector_store, "get_document_chunks", lambda *_: [{"id": "active"}])
    knowledge._run_ingestion("1", "2", str(source), "task", "source.txt", "doc_7", False, 9)
    assert ingest.call_args.kwargs["index_generation"] == 9
    updated.assert_called_once_with("task", "done", chunks=1, document_id="doc_7")
    assert source.exists()


def test_durable_ingestion_reports_stale_generation_as_conflict(tmp_path, monkeypatch):
    source = tmp_path / "source.txt"
    source.write_text("fixture")
    monkeypatch.setattr(knowledge, "ingestion_task", lambda *_: nullcontext())
    monkeypatch.setattr(knowledge, "ingest_document", Mock(side_effect=StaleGeneration("解析代已过时，拒绝重放")))
    request = DocumentIngestRequest(user_id="1", kb_id="2", file_path=str(source),
                                   task_id="task", document_id="doc_7", index_generation=1)
    with pytest.raises(HTTPException) as conflict:
        asyncio.run(knowledge.ingest_durable(request))
    assert conflict.value.status_code == 409
    assert "解析代已过时" in conflict.value.detail


def test_cancelled_document_endpoint_does_not_permanently_delete_id(monkeypatch):
    cancel = Mock(return_value=3)
    delete = Mock()
    monkeypatch.setattr(knowledge.vector_store, "cancel_document", cancel)
    monkeypatch.setattr(knowledge.vector_store, "delete_document", delete)
    assert asyncio.run(knowledge.cancel_document("doc_7", "1", "2")) == {"deleted_chunks": 3, "document_id": "doc_7"}
    cancel.assert_called_once_with("1", "2", "doc_7")
    delete.assert_not_called()
