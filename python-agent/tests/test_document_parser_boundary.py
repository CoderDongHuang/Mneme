"""Parsing must remain usable without initializing indexing backends."""

import subprocess
import sys
from pathlib import Path


def test_parser_reads_source_without_importing_index_backends(tmp_path):
    source = tmp_path / "stored-name.txt"
    source.write_text("Independent parser evidence QZ-7294", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-c", """
import sys
for name in (
    'app.knowledge.ingestion', 'app.knowledge.vector_store',
    'app.knowledge.lexical_index', 'app.knowledge.generations',
    'app.utils.embedding',
):
    sys.modules[name] = None
from app.knowledge.document_parser import parse_document
documents = parse_document(sys.argv[1], 'display-name.txt')
assert len(documents) == 1
assert documents[0].page_content == 'Independent parser evidence QZ-7294'
assert documents[0].metadata['source'] == 'display-name.txt'
assert documents[0].metadata['chunk_type'] == 'text'
""", str(source)],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
