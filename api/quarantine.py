"""Quarantine store for rejected invalid requests."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from common.config import settings
from common.logging import logger


class QuarantineStore:
    """Stores rejected requests along with field-level validation errors."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or settings.QUARANTINE_DB_PATH
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS quarantine_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    correlation_id TEXT,
                    raw_payload TEXT,
                    validation_errors TEXT,
                    created_at TEXT
                )
                """
            )
            conn.commit()

    def quarantine(
        self,
        raw_payload: Any,
        validation_errors: List[Dict[str, Any]],
        correlation_id: str = "unknown",
    ) -> int:
        now = datetime.now(timezone.utc).isoformat()
        payload_str = json.dumps(raw_payload, default=str) if not isinstance(raw_payload, str) else raw_payload
        errors_str = json.dumps(validation_errors, default=str)

        logger.warning(
            f"Quarantining rejected request [corr_id={correlation_id}]: {validation_errors}"
        )

        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO quarantine_records (correlation_id, raw_payload, validation_errors, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (correlation_id, payload_str, errors_str, now),
            )
            conn.commit()
            return cursor.lastrowid

    def list_quarantined(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM quarantine_records ORDER BY id DESC LIMIT ?", (limit,)
            )
            rows = cursor.fetchall()
            return [
                {
                    "id": r["id"],
                    "correlation_id": r["correlation_id"],
                    "raw_payload": json.loads(r["raw_payload"]),
                    "validation_errors": json.loads(r["validation_errors"]),
                    "created_at": r["created_at"],
                }
                for r in rows
            ]

    def count(self) -> int:
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM quarantine_records")
            return cursor.fetchone()[0]


quarantine_store = QuarantineStore()
