"""Agent tools for corpus search, clause lookup, and request field access."""

from __future__ import annotations

import contextvars
from typing import Any, Dict, List, Optional
from common.logging import logger
from retrieval.faiss_loader import index_manager

# Contextvar to hold the active run's request fields
_ACTIVE_REQUEST: contextvars.ContextVar[Dict[str, Any]] = contextvars.ContextVar(
    "active_request", default={}
)


def set_active_request(request_data: Dict[str, Any]) -> None:
    _ACTIVE_REQUEST.set(request_data)


def get_active_request() -> Dict[str, Any]:
    return _ACTIVE_REQUEST.get()


def search_corpus(
    query: str,
    collection: str = "fulltext",
    filters: Optional[Dict[str, Any]] = None,
    top_k: int = 5,
) -> List[Dict[str, Any]]:
    """
    Search the regulatory tariff corpus (GRI rules, Chapter/Section notes, headings, and export policies).
    - query: Search query (e.g. 'vacuum flask', 'stainless steel household articles', 'exclusion note')
    - collection: 'fulltext' or 'headings' (for title/article name lookup)
    - filters: Optional dictionary such as {'type': 'heading'} or {'chapter': '96'}
    - top_k: Number of candidate passages to retrieve (default: 5)
    """
    logger.info(f"Tool search_corpus called: query='{query}', collection='{collection}', filters={filters}")
    results = index_manager.search(query=query, collection=collection, filters=filters, top_k=top_k)
    return [
        {
            "clause_id": r.get("clause_id"),
            "type": r.get("type"),
            "chapter": r.get("chapter"),
            "heading": r.get("heading"),
            "title": r.get("title"),
            "text": r.get("text"),
            "score": r.get("score"),
            "source_doc": r.get("source_doc"),
        }
        for r in results
    ]


def get_clause(clause_id: str) -> Optional[Dict[str, Any]]:
    """
    Retrieve an exact regulatory clause or heading by its unique identifier.
    Examples: 'SEC-XV-NOTE-1M', 'HD9617', 'HD7323', 'GRI-1', 'GRI-3A', 'DGFT-9617'.
    """
    logger.info(f"Tool get_clause called: clause_id='{clause_id}'")
    item = index_manager.get_clause(clause_id)
    if not item:
        return None
    return {
        "clause_id": item.get("clause_id"),
        "type": item.get("type"),
        "chapter": item.get("chapter"),
        "heading": item.get("heading"),
        "title": item.get("title"),
        "text": item.get("text"),
        "source_doc": item.get("source_doc"),
        "metadata": item.get("metadata", {}),
    }


def get_request_fields(field_name: Optional[str] = None) -> Any:
    """
    Retrieve fields submitted in the product classification request.
    Can return all fields or a specific field (e.g., 'description', 'materials', 'intended_use').
    """
    req = get_active_request()
    logger.info(f"Tool get_request_fields called: field_name='{field_name}'")
    if field_name:
        return req.get(field_name)
    return req
