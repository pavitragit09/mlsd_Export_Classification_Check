"""Idempotent CLI entrypoint to parse, chunk, embed, and index the regulatory corpus."""

from __future__ import annotations

import os
import sys
from typing import Optional
from common.config import settings
from common.logging import logger
from ingestion.corpus_downloader import ensure_corpus
from ingestion.parser import CorpusParser
from ingestion.chunker import CorpusChunker
from ingestion.indexer import CorpusIndexer


def run_ingest(corpus_dir: Optional[str] = None) -> None:
    target_corpus = corpus_dir or ("data/corpus" if os.path.exists("data/corpus") else settings.CORPUS_DIR)
    logger.info(f"Starting corpus ingestion pipeline using: {target_corpus}")
    ensure_corpus(target_corpus)

    parser = CorpusParser(corpus_dir=target_corpus)
    records = parser.load_all()
    if not records:
        logger.error(f"No records found in {target_corpus}. Aborting ingestion.")
        sys.exit(1)

    chunker = CorpusChunker()
    chunks = chunker.chunk_records(records)
    logger.info(f"Generated {len(chunks)} structured chunks.")

    indexer = CorpusIndexer(
        index_dir=settings.INDEX_DIR,
        model_name=settings.EMBEDDING_MODEL,
    )
    manifest = indexer.build_indexes(chunks)
    logger.info(f"Ingestion completed successfully. Total chunks: {manifest['chunk_count_fulltext']}")


if __name__ == "__main__":
    run_ingest()
