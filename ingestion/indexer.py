"""Vector indexer building two FAISS indices (full-text and heading-titles) and manifest."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from typing import List
import faiss
import numpy as np
from sentence_transformers import SentenceTransformer
from common.config import settings
from common.logging import logger
from ingestion.chunker import Chunk


class CorpusIndexer:
    """Creates FAISS indexes for full-text chunks and heading-titles-only."""

    def __init__(
        self,
        index_dir: str = "data/index",
        model_name: str = "all-MiniLM-L6-v2",
    ):
        self.index_dir = index_dir
        self.model_name = model_name
        os.makedirs(self.index_dir, exist_ok=True)
        logger.info(f"Loading embedding model: {self.model_name}")
        self.encoder = SentenceTransformer(self.model_name)

    def build_indexes(self, chunks: List[Chunk]) -> dict:
        t_start = time.perf_counter()

        # 1. Collection A: Full-text chunks
        fulltext_texts = [c.text for c in chunks]
        fulltext_meta = [c.model_dump() for c in chunks]

        logger.info(f"Embedding {len(fulltext_texts)} fulltext chunks...")
        ft_embeddings = self.encoder.encode(fulltext_texts, show_progress_bar=False, normalize_embeddings=True)
        ft_dim = ft_embeddings.shape[1]

        ft_index = faiss.IndexFlatIP(ft_dim)
        ft_index.add(np.array(ft_embeddings, dtype=np.float32))

        ft_index_path = os.path.join(self.index_dir, "fulltext.index")
        ft_meta_path = os.path.join(self.index_dir, "fulltext_meta.json")
        faiss.write_index(ft_index, ft_index_path)
        with open(ft_meta_path, "w", encoding="utf-8") as f:
            json.dump(fulltext_meta, f, indent=2)

        # 2. Collection B: Heading-titles-only chunks
        heading_chunks = [c for c in chunks if c.type == "heading" or c.heading]
        hd_texts = [f"Heading {c.heading}: {c.title}" for c in heading_chunks]
        hd_meta = [c.model_dump() for c in heading_chunks]

        logger.info(f"Embedding {len(hd_texts)} heading-title chunks...")
        hd_embeddings = self.encoder.encode(hd_texts, show_progress_bar=False, normalize_embeddings=True)
        hd_dim = hd_embeddings.shape[1]

        hd_index = faiss.IndexFlatIP(hd_dim)
        hd_index.add(np.array(hd_embeddings, dtype=np.float32))

        hd_index_path = os.path.join(self.index_dir, "headings.index")
        hd_meta_path = os.path.join(self.index_dir, "headings_meta.json")
        faiss.write_index(hd_index, hd_index_path)
        with open(hd_meta_path, "w", encoding="utf-8") as f:
            json.dump(hd_meta, f, indent=2)

        duration = time.perf_counter() - t_start

        # 3. Write Index Manifest
        manifest = {
            "build_time": datetime.now(timezone.utc).isoformat(),
            "embedding_model": self.model_name,
            "embedding_dimension": ft_dim,
            "chunk_count_fulltext": len(chunks),
            "chunk_count_headings": len(heading_chunks),
            "build_duration_seconds": round(duration, 3),
            "source_versions": {
                "gri": "CBIC Customs Tariff GRI 2023",
                "chapter_73": "CBIC Customs Tariff Chapter 73 (Iron/Steel)",
                "chapter_96": "CBIC Customs Tariff Chapter 96 (Misc Manufactured)",
                "dgft_policy": "DGFT Export Policy Schedule 2 (2023)",
            },
        }
        manifest_path = os.path.join(self.index_dir, "manifest.json")
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

        logger.info(f"Index built successfully in {duration:.2f}s: {manifest}")
        return manifest
