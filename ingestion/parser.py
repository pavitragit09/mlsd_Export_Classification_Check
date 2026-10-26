"""Parser for Customs Tariff notes, headings, GRI rules, and DGFT policy files."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List
from common.logging import logger


class CorpusParser:
    """Parses structured JSON and raw corpus documents into standard record dictionaries."""

    def __init__(self, corpus_dir: str = "data/sample"):
        self.corpus_dir = corpus_dir

    def load_all(self) -> List[Dict[str, Any]]:
        records: List[Dict[str, Any]] = []
        if not os.path.exists(self.corpus_dir):
            logger.warning(f"Corpus directory {self.corpus_dir} does not exist.")
            return records

        for filename in sorted(os.listdir(self.corpus_dir)):
            if filename.endswith(".json"):
                filepath = os.path.join(self.corpus_dir, filename)
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        if isinstance(data, list):
                            records.extend(data)
                        elif isinstance(data, dict):
                            records.append(data)
                        logger.info(f"Loaded {len(data)} items from {filename}")
                except Exception as e:
                    logger.error(f"Failed parsing {filepath}: {e}")

        logger.info(f"Total raw records parsed: {len(records)}")
        return records
