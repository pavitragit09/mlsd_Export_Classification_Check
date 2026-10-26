"""Idempotent CLI entrypoint to parse, chunk, embed, and index the regulatory corpus."""

from __future__ import annotations

import sys
from common.config import settings
from common.logging import logger
from ingestion.corpus_downloader import ensure_corpus
from ingestion.parser import CorpusParser
from ingestion.chunker import CorpusChunker
from ingestion.indexer import CorpusIndexer


def run_ingest() -> None:
    logger.info("Starting corpus ingestion pipeline...")
    ensure_corpus(settings.CORPUS_DIR)

    parser = CorpusParser(corpus_dir=settings.CORPUS_DIR)
    records = parser.load_all()
    if not records:
        logger.error(f"No records found in {settings.CORPUS_DIR}. Aborting ingestion.")
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
