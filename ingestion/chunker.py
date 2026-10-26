"""Structural chunking ensuring one chunk per heading, note, GRI rule, or policy row."""

from __future__ import annotations

from typing import Any, Dict, List
from pydantic import BaseModel, Field


class Chunk(BaseModel):
    chunk_id: str
    clause_id: str
    type: str  # 'heading' | 'note' | 'gri' | 'policy'
    chapter: str = ""
    heading: str = ""
    title: str = ""
    text: str = ""
    source_doc: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)


class CorpusChunker:
    """Produces structured chunks preserving regulatory boundaries and metadata."""

    def chunk_records(self, raw_records: List[Dict[str, Any]]) -> List[Chunk]:
        chunks: List[Chunk] = []

        for item in raw_records:
            clause_id = item.get("clause_id", "")
            chunk_type = item.get("type", "unknown")
            chapter = str(item.get("chapter", ""))
            heading = str(item.get("heading", ""))
            title = item.get("title", "")
            text = item.get("text", "")
            source_doc = item.get("source_doc", "")

            # Formulate full descriptive text for full-text search
            content_parts = []
            if title:
                content_parts.append(title)
            if heading:
                content_parts.append(f"Heading: {heading}")
            if text:
                content_parts.append(text)
            full_text = "\n".join(content_parts)

            chunk = Chunk(
                chunk_id=clause_id or f"{chunk_type}-{len(chunks)}",
                clause_id=clause_id,
                type=chunk_type,
                chapter=chapter,
                heading=heading,
                title=title,
                text=full_text,
                source_doc=source_doc,
                metadata={
                    "rule_number": item.get("rule_number"),
                    "policy_status": item.get("policy_status"),
                    "conditions": item.get("conditions"),
                    "section": item.get("section"),
                },
            )
            chunks.append(chunk)

        return chunks
