"""Tests for vector retrieval of heading 9617 and exclusion notes."""

from retrieval.faiss_loader import index_manager
from retrieval.tools import search_corpus, get_clause


def test_retrieval_heading_9617():
    # Search heading titles index by article name
    results = search_corpus(
        query="vacuum flask",
        collection="headings",
        top_k=3,
    )
    assert len(results) > 0
    top_headings = [r.get("heading") for r in results]
    assert "9617" in top_headings, f"Expected 9617 in top headings, got: {top_headings}"


def test_retrieval_section_xv_exclusion_note():
    # Search notes for vacuum flask exclusion
    results = search_corpus(
        query="vacuum flasks excluded Chapter 96",
        collection="fulltext",
        filters={"type": "note"},
        top_k=3,
    )
    assert len(results) > 0
    found_note_1m = any("SEC-XV-NOTE-1M" == r.get("clause_id") or "9617" in r.get("text", "") for r in results)
    assert found_note_1m, "Expected Section XV Note 1(m) or Chapter 96 exclusion note in retrieved notes"


def test_get_clause_by_id():
    clause_9617 = get_clause("HD9617")
    assert clause_9617 is not None
    assert clause_9617["heading"] == "9617"
    assert "vacuum flasks" in clause_9617["title"].lower()

    clause_note = get_clause("SEC-XV-NOTE-1M")
    assert clause_note is not None
    assert "vacuum flasks" in clause_note["text"].lower()
