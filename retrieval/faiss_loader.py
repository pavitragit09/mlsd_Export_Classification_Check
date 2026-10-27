"""FAISS index loader supporting dual collections (fulltext & headings) and clause lookup."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional
import faiss
import numpy as np
from sentence_transformers import SentenceTransformer
from common.config import settings
from common.logging import logger


class IndexManager:
    """Manages loaded FAISS indices and metadata."""

    def __init__(self, index_dir: Optional[str] = None, model_name: Optional[str] = None):
        self.index_dir = index_dir or settings.INDEX_DIR
        self.model_name = model_name or settings.EMBEDDING_MODEL

        self.encoder: Optional[SentenceTransformer] = None
        self.ft_index: Optional[faiss.IndexFlatIP] = None
        self.ft_meta: List[Dict[str, Any]] = []

        self.hd_index: Optional[faiss.IndexFlatIP] = None
        self.hd_meta: List[Dict[str, Any]] = []

        self.manifest: Dict[str, Any] = {}
        self._clause_map: Dict[str, Dict[str, Any]] = {}

        self._load()

    def _load(self) -> None:
        ft_idx_path = os.path.join(self.index_dir, "fulltext.index")
        ft_meta_path = os.path.join(self.index_dir, "fulltext_meta.json")
        hd_idx_path = os.path.join(self.index_dir, "headings.index")
        hd_meta_path = os.path.join(self.index_dir, "headings_meta.json")
        manifest_path = os.path.join(self.index_dir, "manifest.json")

        if not os.path.exists(ft_idx_path) or not os.path.exists(hd_idx_path):
            logger.info("Indices not found on disk. Automatically running ingestion pipeline...")
            try:
                from ingestion.ingest import run_ingest
                run_ingest()
            except Exception as e:
                logger.error(f"Auto-ingestion failed: {e}")

        if os.path.exists(ft_idx_path) and os.path.exists(ft_meta_path):
            self.ft_index = faiss.read_index(ft_idx_path)
            with open(ft_meta_path, "r", encoding="utf-8") as f:
                self.ft_meta = json.load(f)
            for item in self.ft_meta:
                cid = item.get("clause_id")
                if cid:
                    self._clause_map[cid.upper()] = item
            logger.info(f"Loaded fulltext index with {len(self.ft_meta)} chunks.")

        if os.path.exists(hd_idx_path) and os.path.exists(hd_meta_path):
            self.hd_index = faiss.read_index(hd_idx_path)
            with open(hd_meta_path, "r", encoding="utf-8") as f:
                self.hd_meta = json.load(f)
            for item in self.hd_meta:
                cid = item.get("clause_id")
                if cid:
                    self._clause_map[cid.upper()] = item
            logger.info(f"Loaded headings index with {len(self.hd_meta)} chunks.")

        if os.path.exists(manifest_path):
            with open(manifest_path, "r", encoding="utf-8") as f:
                self.manifest = json.load(f)

    def _get_encoder(self) -> SentenceTransformer:
        if self.encoder is None:
            self.encoder = SentenceTransformer(self.model_name)
        return self.encoder

    def search(
        self,
        query: str,
        collection: str = "fulltext",
        filters: Optional[Dict[str, Any]] = None,
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        is_heading_col = collection.lower() in ["headings", "heading_titles", "titles"]
        index = self.hd_index if is_heading_col else self.ft_index
        meta = self.hd_meta if is_heading_col else self.ft_meta

        if index is None or not meta:
            logger.warning(f"Collection {collection} is not loaded.")
            return []

        encoder = self._get_encoder()
        query_vec = encoder.encode([query], normalize_embeddings=True)
        query_arr = np.array(query_vec, dtype=np.float32)

        # Retrieve top 2 * top_k to allow post-filtering
        k_search = min(len(meta), max(top_k * 3, 10))
        scores, indices = index.search(query_arr, k_search)

        results: List[Dict[str, Any]] = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0 or idx >= len(meta):
                continue
            item = meta[idx].copy()
            item["score"] = float(score)

            # Apply filters if any
            if filters:
                match = True
                for f_key, f_val in filters.items():
                    val = item.get(f_key)
                    if isinstance(f_val, list):
                        if val not in f_val:
                            match = False
                            break
                    elif str(val).lower() != str(f_val).lower():
                        match = False
                        break
                if not match:
                    continue

            results.append(item)
            if len(results) >= top_k:
                break

        return results

    def get_clause(self, clause_id: str) -> Optional[Dict[str, Any]]:
        return self._clause_map.get(clause_id.strip().upper())


# Global singleton instance
index_manager = IndexManager()
