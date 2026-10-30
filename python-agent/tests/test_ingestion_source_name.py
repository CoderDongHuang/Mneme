import asyncio
from contextlib import nullcontext
from unittest.mock import Mock

import pytest

from app.api import knowledge
from app.models.knowledge import DocumentIngestRequest


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
