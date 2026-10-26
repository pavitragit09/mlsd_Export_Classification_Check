"""Tests for structural chunking and metadata preservation."""

from ingestion.parser import CorpusParser
from ingestion.chunker import CorpusChunker


def test_corpus_chunker_metadata_preservation():
    parser = CorpusParser(corpus_dir="data/sample")
    raw_records = parser.load_all()
    assert len(raw_records) > 0

    chunker = CorpusChunker()
    chunks = chunker.chunk_records(raw_records)
    assert len(chunks) == len(raw_records)

    types = {c.type for c in chunks}
    assert "heading" in types
    assert "note" in types
    assert "gri" in types
    assert "policy" in types

    # Verify metadata fields exist on every chunk
    for c in chunks:
        assert c.clause_id, f"Missing clause_id on chunk: {c}"
        assert c.type in ["heading", "note", "gri", "policy", "unknown"]
        assert c.text, f"Empty text on chunk: {c.clause_id}"


def test_specific_clause_structures():
    chunker = CorpusChunker()
    sample = [
        {
            "clause_id": "HD9617",
            "type": "heading",
            "chapter": "96",
            "heading": "9617",
            "title": "Vacuum flasks",
            "text": "Vacuum flasks text",
            "source_doc": "CBIC Chapter 96",
        }
    ]
    chunks = chunker.chunk_records(sample)
    assert len(chunks) == 1
    assert chunks[0].heading == "9617"
    assert chunks[0].chapter == "96"
    assert chunks[0].type == "heading"
