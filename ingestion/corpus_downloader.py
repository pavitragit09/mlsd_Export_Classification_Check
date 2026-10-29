"""Corpus downloader / sample checker."""

from __future__ import annotations

import os
from typing import Optional
from common.logging import logger


def ensure_corpus(corpus_dir: Optional[str] = None) -> bool:
    """Verifies that the corpus files exist; logs instructions if missing."""
    if corpus_dir is None:
        corpus_dir = "data/corpus" if os.path.exists("data/corpus") else "data/sample"
    if not os.path.exists(corpus_dir):
        os.makedirs(corpus_dir, exist_ok=True)

    required_files = ["gri.json", "section_notes.json", "chapter_73.json", "chapter_96.json", "dgft_policy.json"]
    missing = [f for f in required_files if not os.path.exists(os.path.join(corpus_dir, f))]

    if missing:
        logger.warning(
            f"Missing corpus files in {corpus_dir}: {missing}. "
            "Please consult data/README.md for official download sources."
        )
        return False

    logger.info(f"All {len(required_files)} standard corpus files present in {corpus_dir}.")
    return True
